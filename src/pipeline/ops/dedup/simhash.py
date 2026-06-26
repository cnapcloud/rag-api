"""SimHash-based duplicate detection (SHA-256 title + SimHash body)."""

from __future__ import annotations

import hashlib
import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Generator

from pipeline.ops.dedup.types import DedupResult

if TYPE_CHECKING:
    import redis as redis_lib

    from config.settings import DedupSettings

logger = logging.getLogger(__name__)

_BAND_KEY = "dedup:band:{band_idx}:{band_val}"
_SIMHASH_KEY = "dedup:simhash:{doc_id}"
_TITLE_HASH_KEY = "dedup:titlehash:{doc_id}"
_LOCK_KEY = "dedup:lock:{band_idx}:{band_val}"


# ──────────────────────────────────────────────
# Hash utilities
# ──────────────────────────────────────────────

def compute_title_hash(title: str) -> str:
    """Return SHA-256 hex digest of the normalized title."""
    return hashlib.sha256(title.strip().encode()).hexdigest()


def compute_simhash(text: str, ngram: int = 3, bits: int = 64) -> int:
    """Compute SimHash of text using character-level n-grams.

    Slides a window of `ngram` characters over the text (spaces included).
    Returns a `bits`-wide integer.
    """
    v = [0] * bits
    mask = (1 << bits) - 1

    for i in range(max(0, len(text) - ngram + 1)):
        shingle = text[i : i + ngram]
        h = int(hashlib.md5(shingle.encode()).hexdigest(), 16) & mask
        for bit in range(bits):
            if h & (1 << bit):
                v[bit] += 1
            else:
                v[bit] -= 1

    result = 0
    for bit in range(bits):
        if v[bit] > 0:
            result |= 1 << bit
    return result


def u64_to_i64(value: int) -> int:
    """Reinterpret an unsigned 64-bit SimHash as a signed int64 for PostgreSQL BIGINT storage."""
    return value if value < (1 << 63) else value - (1 << 64)


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def get_bands(simhash: int, num_bands: int = 4, bits: int = 64) -> list[tuple[int, str]]:
    """Split simhash into num_bands equal slices. Returns list of (band_idx, band_val_hex)."""
    band_bits = bits // num_bands
    mask = (1 << band_bits) - 1
    bands = []
    for i in range(num_bands):
        val = (simhash >> (i * band_bits)) & mask
        bands.append((i, format(val, f"0{band_bits // 4}x")))
    return bands


# ──────────────────────────────────────────────
# Redis band lock
# ──────────────────────────────────────────────

@contextmanager
def _acquire_band_locks(
    rc: redis_lib.Redis,
    bands: list[tuple[int, str]],
    lock_ttl: int,
    lock_acquire_timeout: int,
) -> Generator[bool, None, None]:
    """Acquire SETNX locks on all band keys. Releases on exit.

    Yields True if all locks acquired, False if timeout exceeded (caller should proceed without lock).
    """
    lock_keys = [_LOCK_KEY.format(band_idx=i, band_val=v) for i, v in bands]
    acquired: list[str] = []
    deadline = time.monotonic() + lock_acquire_timeout

    try:
        for key in lock_keys:
            while time.monotonic() < deadline:
                if rc.set(key, "1", nx=True, ex=lock_ttl):
                    acquired.append(key)
                    break
                time.sleep(0.05)
            else:
                logger.warning("Band lock timeout: key=%s — proceeding without full lock", key)
                yield False
                return
        yield True
    finally:
        for key in acquired:
            rc.delete(key)


# ──────────────────────────────────────────────
# Detection
# ──────────────────────────────────────────────

def run_simhash_detection(
    doc_id: str,
    title: str,
    body: str,
    rc: redis_lib.Redis,
    cfg: DedupSettings,
) -> DedupResult:
    """Run SimHash-based duplicate detection.

    Steps:
      1. Compute title_hash (SHA-256) and body simhash.
      2. Acquire band-level Redis locks.
      3. SUNION band sets to find candidate doc_ids.
      4. For each candidate, compute Hamming distance.
      5. If Hamming <= threshold: compare title_hash to determine verdict.
      6. SADD new doc to band sets + store simhash/title_hash (for future comparisons).
      7. Release locks.
    """
    title_hash = compute_title_hash(title)
    simhash = compute_simhash(body, ngram=cfg.ngram, bits=cfg.simhash_bits)
    bands = get_bands(simhash, num_bands=cfg.num_bands, bits=cfg.simhash_bits)

    band_set_keys = [_BAND_KEY.format(band_idx=i, band_val=v) for i, v in bands]

    with _acquire_band_locks(rc, bands, cfg.lock_ttl, cfg.lock_acquire_timeout):
        # Find candidates via SUNION
        raw_candidates: set[str] = rc.sunion(*band_set_keys)  # type: ignore[arg-type]
        candidates = raw_candidates - {doc_id}

        # Fetch stored simhashes for candidates in one round-trip
        if candidates:
            simhash_keys = [_SIMHASH_KEY.format(doc_id=cid) for cid in candidates]
            stored_hashes = rc.mget(*simhash_keys)
        else:
            stored_hashes = []

        close_candidates: list[tuple[str, int]] = []
        for cid, raw_hash in zip(candidates, stored_hashes):
            if raw_hash is None:
                continue
            cand_simhash = int(raw_hash)
            dist = hamming_distance(simhash, cand_simhash)
            if dist <= cfg.hamming_identical_threshold:
                close_candidates.append((cid, dist))

        close_candidates.sort(key=lambda x: x[1])

        result: DedupResult
        if close_candidates:
            best_doc_id, best_dist = close_candidates[0]
            stored_title = rc.get(_TITLE_HASH_KEY.format(doc_id=best_doc_id))
            title_changed = stored_title != title_hash

            logger.info(
                "Body: near-identical doc_id=%s duplicate=%s hamming_dist=%d",
                doc_id, best_doc_id, best_dist,
            )
            if title_changed:
                logger.info("Title: changed doc_id=%s duplicate=%s", doc_id, best_doc_id)
            else:
                logger.info("Title: unchanged doc_id=%s duplicate=%s", doc_id, best_doc_id)

            if not title_changed:
                result = DedupResult(
                    verdict="identical",
                    duplicate_doc_id=best_doc_id,
                    needs_indexing=False,
                    title_hash=title_hash,
                    content_simhash=simhash,
                    candidate_doc_ids=[cid for cid, _ in close_candidates],
                )
            else:
                result = DedupResult(
                    verdict="title_changed",
                    duplicate_doc_id=best_doc_id,
                    needs_indexing=False,
                    title_hash=title_hash,
                    content_simhash=simhash,
                    candidate_doc_ids=[cid for cid, _ in close_candidates],
                )
        else:
            logger.info("Body: no near-duplicate found doc_id=%s", doc_id)
            logger.info("Title: no candidate to compare doc_id=%s", doc_id)
            result = DedupResult(
                verdict="proceed",
                needs_indexing=True,
                title_hash=title_hash,
                content_simhash=simhash,
                candidate_doc_ids=[],
            )

        # Register new doc in band index only when proceeding to indexing
        if result.needs_indexing:
            for key in band_set_keys:
                rc.sadd(key, doc_id)
            rc.set(_SIMHASH_KEY.format(doc_id=doc_id), str(simhash))
            rc.set(_TITLE_HASH_KEY.format(doc_id=doc_id), title_hash)

    return result
