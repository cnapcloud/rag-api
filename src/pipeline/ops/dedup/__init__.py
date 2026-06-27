"""Dedup pipeline — SimHash detection and verdict handling."""

from __future__ import annotations

import logging

from pipeline.ops.dedup.simhash import run_simhash_detection
from pipeline.ops.dedup.types import DedupResult, DedupVerdict
from pipeline.ops.dedup.verdict import run_verdict

logger = logging.getLogger(__name__)

__all__ = ["run_dedup_pipeline", "run_simhash_detection", "run_verdict", "DedupResult", "DedupVerdict"]


def run_dedup_pipeline(
    doc_id: str,
    run_id: str = "direct",
    documents=None,
) -> DedupResult:
    """Run the full dedup pipeline for a single document (runner.py / non-Dagster path).

    If documents is provided (pre-parsed), skips the internal parse step.
    Otherwise downloads and parses the document from S3 (backfill / standalone use).

    Returns DedupResult; caller uses needs_indexing to decide whether to
    proceed to chunk/embed/upsert.
    """
    from config.settings import get_settings
    from infra.redis import get_redis_client

    cfg = get_settings()
    if not cfg.dedup.enabled:
        logger.info("Dedup disabled: doc_id=%s", doc_id)
        return DedupResult(verdict="proceed", needs_indexing=True)

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

    result = run_simhash_detection(
        doc_id=doc_id,
        title=title,
        body=body,
        rc=get_redis_client(),
        cfg=cfg.dedup,
    )
    run_verdict(doc_id=doc_id, result=result, run_id=run_id)
    return result
