"""Chunk-level comparison (dedup stage 3): embedding cosine similarity + threshold body verdict.

Confirms simhash/minhash stage 'similar' results by comparing A's chunks (computed
in-memory, not indexed) against a candidate C's already-indexed Qdrant chunks.

Algorithm (docs/internal/design/dedup.md 3.3.2 / 3.3.3):
  1. Chunk + embed A in-memory (pipeline/ops/chunk.chunk + pipeline/ops/embed.embed).
  2. For each A chunk, search C's chunks in Qdrant (dense-only), keep hits >= chunk_match_threshold,
     take the Top-1 (highest score).
  3. Aggregate to a document-level score: coverage-weighted average = sum(matched scores) / N,
     where N is A's total chunk count (unmatched chunks count as 0).
  4. Map the aggregate score to body_match via body_identical_threshold / body_similar_threshold.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rag_api.pipeline.ops.dedup.types import BodyMatch, DedupResult

if TYPE_CHECKING:
    from llama_index.core import Document

    from rag_api.config.settings import DedupSettings

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 5


@dataclass
class ChunkMatch:
    a_chunk_index: int
    c_point_id: str
    score: float


@dataclass
class ChunkCompareScore:
    candidate_doc_id: str
    aggregate_score: float
    matches: list[ChunkMatch] = field(default_factory=list)


def compare_chunks(
    kb_id: str,
    doc_id: str,
    documents: list[Document],
    candidate_doc_id: str,
    cfg: DedupSettings,
    top_k: int = _DEFAULT_TOP_K,
) -> ChunkCompareScore:
    """Compute the document-level aggregate score between A and a single candidate C.

    A is chunked and embedded in-memory (not upserted to Qdrant); only C's already-indexed
    chunks are searched. See known-issues.md #14 for the accepted double-computation cost.
    """
    from rag_api.infra.qdrant import search_chunks_by_doc_id
    from rag_api.pipeline.ops.chunk import chunk
    from rag_api.pipeline.ops.embed import embed

    nodes = chunk(documents)
    if not nodes:
        logger.info("chunk_compare: no chunks for doc_id=%s candidate=%s", doc_id, candidate_doc_id)
        return ChunkCompareScore(candidate_doc_id=candidate_doc_id, aggregate_score=0.0)

    embedded_nodes = embed(nodes)

    matches: list[ChunkMatch] = []
    total_score = 0.0
    for idx, en in enumerate(embedded_nodes):
        hits = search_chunks_by_doc_id(
            kb_id=kb_id,
            doc_id=candidate_doc_id,
            query_vector=en.dense_vector,
            top_k=top_k,
        )
        passed = [(pid, score) for pid, score in hits if score >= cfg.chunk_match_threshold]
        if not passed:
            continue
        pid, score = max(passed, key=lambda hit: hit[1])
        matches.append(ChunkMatch(a_chunk_index=idx, c_point_id=pid, score=score))
        total_score += score

    aggregate_score = total_score / len(embedded_nodes)
    logger.info(
        "chunk_compare: doc_id=%s candidate=%s matched=%d/%d aggregate_score=%.3f",
        doc_id, candidate_doc_id, len(matches), len(embedded_nodes), aggregate_score,
    )
    return ChunkCompareScore(candidate_doc_id=candidate_doc_id, aggregate_score=aggregate_score, matches=matches)


def score_to_body_match(aggregate_score: float, cfg: DedupSettings) -> BodyMatch:
    """Map a chunk_compare aggregate score to a body_match band."""
    if aggregate_score >= cfg.body_identical_threshold:
        return "identical_level"
    if aggregate_score >= cfg.body_similar_threshold:
        return "similar"
    return "none"


def run_chunk_compare(
    doc_id: str,
    kb_id: str,
    documents: list[Document],
    result: DedupResult,
    cfg: DedupSettings,
) -> DedupResult:
    """Route a stage1/2 'similar' result through chunk-level comparison to confirm body.

    Only meaningful when result.body_match == 'similar'. Compares against
    result.duplicate_doc_id (best match) by default, or all of result.candidate_doc_ids
    when cfg.compare_all_candidates. The highest aggregate score wins (identical-band
    scores are always higher than similar-band scores, so this naturally prioritizes
    identical matches when multiple candidates qualify).
    """
    candidates = (
        result.candidate_doc_ids
        if cfg.compare_all_candidates
        else ([result.duplicate_doc_id] if result.duplicate_doc_id else [])
    )
    if not candidates:
        logger.info("chunk_compare: no candidates to compare doc_id=%s", doc_id)
        return DedupResult(body_match="none", needs_indexing=True)

    scored = [
        (cid, compare_chunks(kb_id=kb_id, doc_id=doc_id, documents=documents, candidate_doc_id=cid, cfg=cfg).aggregate_score)
        for cid in candidates
    ]
    best_doc_id, best_score = max(scored, key=lambda s: s[1])
    body_match = score_to_body_match(best_score, cfg)
    passed_candidates = [cid for cid, score in scored if score_to_body_match(score, cfg) != "none"]

    if body_match == "none":
        logger.info(
            "chunk_compare: no candidate confirmed doc_id=%s best_score=%.3f", doc_id, best_score
        )
        return DedupResult(body_match="none", needs_indexing=True)

    logger.info(
        "chunk_compare: confirmed body_match=%s doc_id=%s duplicate=%s score=%.3f",
        body_match, doc_id, best_doc_id, best_score,
    )
    return DedupResult(
        body_match=body_match,
        title_match=result.title_match,
        duplicate_doc_id=best_doc_id,
        needs_indexing=False,
        title_hash=result.title_hash,
        content_simhash=result.content_simhash,
        candidate_doc_ids=passed_candidates,
    )
