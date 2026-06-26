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
) -> DedupResult:
    """Run the full dedup pipeline for a single document (runner.py / non-Dagster path).

    Downloads the document from MinIO internally — same as dedup_job's simhash_op.
    Currently implements stage 1 (SimHash + SHA-256 title hash).
    Stages 2-5 will be added here as implemented.

    Returns DedupResult; caller uses needs_indexing to decide whether to
    proceed to parse/chunk/embed/upsert.
    """
    from config.settings import get_settings
    from exceptions import IngestValidationError
    from infra.postgres import get_doc_by_id
    from infra.redis import get_redis_client
    from pipeline.ops.parse import parse

    cfg = get_settings()
    if not cfg.dedup.enabled:
        logger.info("Dedup disabled: doc_id=%s", doc_id)
        return DedupResult(verdict="proceed", needs_indexing=True)

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
