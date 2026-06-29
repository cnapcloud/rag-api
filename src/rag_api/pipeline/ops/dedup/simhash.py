"""SimHash-based duplicate detection (SHA-256 title + SimHash body)."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from rag_api.pipeline.ops.dedup.types import BodyMatch, DedupResult, TitleMatch

if TYPE_CHECKING:
    from rag_api.config.settings import DedupSettings

logger = logging.getLogger(__name__)


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


def i64_to_u64(value: int) -> int:
    """Reinterpret a signed int64 from PostgreSQL BIGINT as an unsigned 64-bit SimHash."""
    return value if value >= 0 else value + (1 << 64)


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
# Detection
# ──────────────────────────────────────────────

def run_simhash_detection(
    doc_id: str,
    title: str,
    body: str,
    cfg: DedupSettings,
    kb_id: str = "",
) -> DedupResult:
    """Run SimHash-based duplicate detection using Postgres band index.

    Steps:
      1. Compute title_hash (SHA-256) and body simhash.
      2. Query simhash_bands for candidate doc_ids sharing any band.
      3. Batch-fetch candidate fingerprints (content_simhash, title_hash).
      4. For each candidate, compute Hamming distance.
      5. If Hamming <= threshold: compare title_hash to determine verdict.
      6. Save new doc to simhash_bands (only when proceeding to indexing).
      7. Persist title_hash and content_simhash to documents table.
    """
    from rag_api.infra.postgres import (
        find_simhash_candidates,
        get_docs_fingerprints,
        save_simhash_bands,
        update_doc_fields,
    )

    title_hash = compute_title_hash(title)
    simhash = compute_simhash(body, ngram=cfg.ngram, bits=cfg.simhash_bits)
    bands = get_bands(simhash, num_bands=cfg.num_bands, bits=cfg.simhash_bits)

    candidates = find_simhash_candidates(bands, kb_id=kb_id) - {doc_id}

    fingerprints: dict[str, dict] = {}
    close_candidates: list[tuple[str, int]] = []

    if candidates:
        fingerprints = get_docs_fingerprints(list(candidates))
        for cid, fp in fingerprints.items():
            if fp["content_simhash"] is None:
                continue
            cand_simhash = i64_to_u64(fp["content_simhash"])
            dist = hamming_distance(simhash, cand_simhash)
            if dist <= cfg.hamming_similar_threshold:
                close_candidates.append((cid, dist))

    close_candidates.sort(key=lambda x: x[1])

    if close_candidates:
        best_doc_id, best_dist = close_candidates[0]

        logger.info(
            "Body: near-duplicate found doc_id=%s duplicate=%s hamming_dist=%d",
            doc_id, best_doc_id, best_dist,
        )

        if best_dist <= cfg.hamming_identical_threshold:
            body_match: BodyMatch = "identical_level"
            stored_title = fingerprints.get(best_doc_id, {}).get("title_hash")
            title_match: TitleMatch = "same" if stored_title == title_hash else "changed"
            logger.info("Title: %s doc_id=%s duplicate=%s", title_match, doc_id, best_doc_id)
        else:
            body_match = "similar"
            title_match = "unknown"
            logger.info(
                "Body: similar (not identical) doc_id=%s duplicate=%s hamming_dist=%d",
                doc_id, best_doc_id, best_dist,
            )

        result = DedupResult(
            body_match=body_match,
            title_match=title_match,
            duplicate_doc_id=best_doc_id,
            needs_indexing=False,
            title_hash=title_hash,
            content_simhash=simhash,
            candidate_doc_ids=[cid for cid, _ in close_candidates],
        )
    else:
        logger.info("Body: no near-duplicate found doc_id=%s — proceeding to stage 2", doc_id)
        result = DedupResult(
            body_match="none",
            title_match="unknown",
            needs_indexing=True,
            title_hash=title_hash,
            content_simhash=simhash,
            candidate_doc_ids=[],
        )

    if result.body_match == "none":
        save_simhash_bands(doc_id, bands)

    update_doc_fields(doc_id, {
        "title_hash": title_hash,
        "content_simhash": u64_to_i64(simhash),
    })

    return result
