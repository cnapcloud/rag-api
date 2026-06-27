"""Dedup pipeline — SimHash (stage 1) + MinHash/pg_trgm (stage 2) detection."""

from __future__ import annotations

import logging

from pipeline.ops.dedup.simhash import run_simhash_detection
from pipeline.ops.dedup.types import BodyMatch, DedupResult, TitleMatch
from pipeline.ops.dedup.verdict import run_verdict

logger = logging.getLogger(__name__)

__all__ = ["run_dedup_pipeline", "run_simhash_detection", "run_verdict", "DedupResult",
           "BodyMatch", "TitleMatch"]


def run_dedup_pipeline(
    doc_id: str,
    run_id: str = "direct",
    documents=None,
) -> DedupResult:
    """Run the full dedup pipeline for a single document (runner.py / non-Dagster path).

    Stage 1 (SimHash): detects body similarity level and title match via Hamming distance.
    Stage 2 (MinHash + pg_trgm): runs only when stage 1 body_match is 'none'; detects
    similar documents by Jaccard score and title fuzzy similarity.

    Returns DedupResult; caller uses needs_indexing to decide whether to proceed to
    chunk/embed/upsert.
    """
    from config.settings import get_settings

    cfg = get_settings()
    if not cfg.dedup.enabled:
        logger.info("Dedup disabled: doc_id=%s", doc_id)
        return DedupResult(body_match="none", needs_indexing=True)

    if documents is None:
        from exceptions import IngestValidationError
        from infra.postgres import get_doc_by_id
        from pipeline.ops.parse import parse

        doc = get_doc_by_id(doc_id)
        if doc is None:
            raise IngestValidationError(f"Document not found: doc_id={doc_id}")
        documents = parse(doc_id=doc_id, storage_key=doc.get("storage_key", ""))

    title = " ".join(d.metadata.get("file_name", "") for d in documents[:1])
    body = " ".join(d.text for d in documents)

    # Stage 1: SimHash detection
    result = run_simhash_detection(
        doc_id=doc_id,
        title=title,
        body=body,
        cfg=cfg.dedup,
    )

    # Stage 2: MinHash + pg_trgm (only when stage 1 found no candidates)
    if result.body_match == "none":
        from pipeline.ops.dedup.minhash import run_minhash_detection
        result = run_minhash_detection(doc_id=doc_id, text=body, title=title, cfg=cfg.dedup)

    run_verdict(doc_id=doc_id, result=result, run_id=run_id)
    return result
