"""Stage 2 dedup: MinHash Jaccard + pg_trgm title fuzzy matching.

Algorithm:
  1. Tokenize text with Kiwi morphological analyzer (falls back to whitespace split
     when kiwipiepy is not installed).
  2. Compute a 128-element MinHash signature using universal hashing.
  3. Split into 16 bands x 8 rows; query minhash_bands for candidate docs that share
     all 8 values in at least one band (LSH band approach).
  4. Also query documents.source via pg_trgm for title-similar candidates.
  5. For each candidate, compute Jaccard = matching_positions / 128.
  6. Apply 3-way threshold:
       Jaccard >= jaccard_threshold                              → similar
       title_sim >= title_fuzzy_threshold AND
         Jaccard >= title_only_min_jaccard_floor                → similar
       otherwise                                                → proceed
"""

from __future__ import annotations

import hashlib
import logging
import random
import struct
from typing import TYPE_CHECKING

from pipeline.ops.dedup.tokenizer import get_kiwi
from pipeline.ops.dedup.types import DedupResult

if TYPE_CHECKING:
    from config.settings import DedupSettings

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Kiwi tokenizer with whitespace fallback
# ──────────────────────────────────────────────

_KIWI_NOUN_VERB_TAGS = frozenset(("NNG", "NNP", "NNB", "VV", "VA", "VX"))


def _tokenize(text: str) -> list[str]:
    """Extract content-bearing tokens from text.

    Uses Kiwi morphological analysis when available (Korean + English).
    Falls back to lowercased whitespace splitting.
    """
    kiwi = get_kiwi()
    if kiwi is not None:
        try:
            result = kiwi.tokenize(text)
            tokens = [t.form for t in result if t.tag[:3] in _KIWI_NOUN_VERB_TAGS or t.tag in _KIWI_NOUN_VERB_TAGS]
            return tokens if tokens else text.lower().split()
        except Exception:
            pass
    return text.lower().split()


# ──────────────────────────────────────────────
# MinHash signature computation
# ──────────────────────────────────────────────

_NUM_HASHES = 128
_PRIME = (1 << 61) - 1  # Mersenne prime, ensures uniform distribution


def _build_hash_params(num_hashes: int = _NUM_HASHES, seed: int = 42) -> tuple[list[int], list[int]]:
    rng = random.Random(seed)
    a_vals = [rng.randint(1, _PRIME - 1) for _ in range(num_hashes)]
    b_vals = [rng.randint(0, _PRIME - 1) for _ in range(num_hashes)]
    return a_vals, b_vals


_A_VALS, _B_VALS = _build_hash_params()


def _token_hash(token: str) -> int:
    return int(hashlib.md5(token.encode()).hexdigest(), 16) % _PRIME


def compute_minhash(tokens: list[str], num_hashes: int = _NUM_HASHES) -> list[int]:
    """Compute a MinHash signature from a token list.

    Returns a list of num_hashes integers. Deduplicates tokens (MinHash is set-based).
    Empty input returns a signature of all-PRIME values.
    """
    if not tokens:
        return [_PRIME] * num_hashes

    token_set = set(tokens)
    token_hashes = [_token_hash(t) for t in token_set]

    signature: list[int] = []
    for i in range(num_hashes):
        a, b = _A_VALS[i], _B_VALS[i]
        min_val = min((a * h + b) % _PRIME for h in token_hashes)
        signature.append(min_val)

    return signature


def split_bands(signature: list[int], num_bands: int = 16) -> list[int]:
    """Compute one band hash per band from a MinHash signature.

    Groups consecutive positions into bands and hashes each group to a single int.
    Used for test assertions and lookup query generation.
    """
    n = len(signature)
    rows_per_band = n // num_bands
    band_hashes: list[int] = []
    for b in range(num_bands):
        start = b * rows_per_band
        band_slice = signature[start : start + rows_per_band]
        raw = struct.pack(f">{rows_per_band}Q", *band_slice)
        h = int(hashlib.md5(raw).hexdigest(), 16) % (2**63)
        band_hashes.append(h)
    return band_hashes


def compute_jaccard(sig_a: list[int], sig_b: list[int]) -> float:
    """Estimate Jaccard similarity as matching_positions / total_positions."""
    if not sig_a:
        return 0.0
    matches = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
    return matches / len(sig_a)


# ──────────────────────────────────────────────
# Stage 2 pipeline
# ──────────────────────────────────────────────

def run_minhash_detection(doc_id: str, text: str, title: str, cfg: DedupSettings) -> DedupResult:
    """Detect duplicates via MinHash Jaccard similarity and pg_trgm title fuzzy matching.

    Saves A's MinHash signature to minhash_bands AFTER querying candidates
    (to avoid self-match). Returns DedupResult with verdict 'similar' or 'proceed'.
    """
    from infra.postgres import (
        find_minhash_candidates,
        find_title_candidates,
        get_minhash_signature,
        save_minhash_bands,
    )

    tokens = _tokenize(text)
    signature = compute_minhash(tokens)

    # Query candidates BEFORE saving so A does not match itself.
    body_candidates: set[str] = find_minhash_candidates(signature)
    body_candidates.discard(doc_id)

    title_scores: dict[str, float] = {}
    if title.strip():
        title_scores = find_title_candidates(title, cfg.title_fuzzy_threshold)
        title_scores.pop(doc_id, None)

    # Persist A's signature.
    save_minhash_bands(doc_id, signature)

    all_candidates = body_candidates | set(title_scores)
    if not all_candidates:
        logger.info("no candidates doc_id=%s", doc_id)
        return DedupResult(body_match="none", needs_indexing=True)

    best_doc_id: str | None = None
    best_jaccard = 0.0
    best_title_sim = 0.0
    passed_candidates: list[str] = []

    for cid in all_candidates:
        c_sig = get_minhash_signature(cid)
        if c_sig is None:
            continue
        j = compute_jaccard(signature, c_sig)
        t_sim = title_scores.get(cid, 0.0)

        logger.info(
            "score doc_id=%s cid=%s jaccard=%.3f title_sim=%.3f",
            doc_id, cid, j, t_sim,
        )

        passes = j >= cfg.jaccard_threshold or (
            t_sim >= cfg.title_fuzzy_threshold and j >= cfg.title_only_min_jaccard_floor
        )

        if passes:
            passed_candidates.append(cid)
            if j > best_jaccard:
                best_jaccard = j
                best_doc_id = cid
                best_title_sim = t_sim

    if best_doc_id is not None:
        logger.info(
            "similar found doc_id=%s duplicate=%s jaccard=%.3f title_sim=%.3f",
            doc_id, best_doc_id, best_jaccard, best_title_sim,
        )
        return DedupResult(
            body_match="similar",
            needs_indexing=False,
            duplicate_doc_id=best_doc_id,
            candidate_doc_ids=passed_candidates,
        )

    logger.info("no similar candidate doc_id=%s", doc_id)
    return DedupResult(body_match="none", needs_indexing=True)
