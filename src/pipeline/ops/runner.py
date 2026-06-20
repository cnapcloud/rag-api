"""pipeline/runner.py — Run a single-document pipeline without Dagster."""

from __future__ import annotations

import logging

from config.settings import get_settings

logger = logging.getLogger(__name__)


def run_ingest_pipeline(
    kb_id: str,
    doc_source: str,
    etag: str = "",
    file_size: int = 0,
    force: bool = False,
    run_id: str = "direct",
) -> int:
    """Run ingest pipeline from an S3 object key (downloads from S3 internally)."""
    from exceptions import IngestValidationError
    from infra import postgres as postgres_infra
    from pipeline.ops.chunk import chunk
    from pipeline.ops.embed import embed
    from pipeline.ops.meta import restore_indexed, set_failed, set_processing, update_meta
    from pipeline.ops.parse import parse
    from pipeline.ops.upsert import upsert
    from pipeline.ops.validate import validate

    try:
        should_process = validate(kb_id, doc_source, etag, file_size, force=force)
    except IngestValidationError as e:
        set_failed(kb_id, doc_source, str(e), run_id=run_id)
        logger.error("Validation failed: kb=%s key=%s err=%s", kb_id, doc_source, e)
        raise

    if not should_process:
        current = postgres_infra.get_doc_status(kb_id, doc_source)
        if current and current.get("status") == "running":
            restore_indexed(kb_id, doc_source, etag=etag)
        logger.info("Skipping: kb=%s key=%s", kb_id, doc_source)
        return 0

    set_processing(kb_id, doc_source, run_id=run_id)

    try:
        documents = parse(kb_id=kb_id, doc_source=doc_source)
        nodes = chunk(documents)
        if not nodes:
            raise IngestValidationError("No indexable content: all chunks below min_chunk_chars threshold")
        embedded_nodes = embed(nodes)
        upsert_result = upsert(kb_id, doc_source, embedded_nodes)

        cfg = get_settings().embedding
        update_meta(
            kb_id=kb_id,
            doc_source=doc_source,
            upsert_result=upsert_result,
            etag=etag,
            run_id=run_id,
            file_size=file_size,
            doc_type=doc_source.rsplit(".", 1)[-1],
            embedding_model=cfg.model,
            doc_created_at=upsert_result.doc_created_at,
        )
        logger.info("Ingest done: kb=%s key=%s chunks=%d", kb_id, doc_source, upsert_result.chunk_count)
        return upsert_result.chunk_count

    except Exception as e:
        set_failed(kb_id, doc_source, str(e), run_id=run_id)
        logger.exception("Pipeline failed: kb=%s key=%s", kb_id, doc_source)
        raise


def run_delete_pipeline(kb_id: str, doc_source: str) -> None:
    """Delete a single document from Qdrant and Postgres."""
    from infra import postgres as postgres_infra
    from infra import qdrant as qdrant_infra
    from pipeline.ops.meta import set_deleting, set_failed

    set_deleting(kb_id, doc_source, run_id="direct")
    try:
        qdrant_infra.delete_chunks_by_doc(kb_id, doc_source)
        postgres_infra.delete_doc_meta(kb_id, doc_source)
        logger.info("Delete done: kb=%s key=%s", kb_id, doc_source)
    except Exception as e:
        set_failed(kb_id, doc_source, f"delete_pipeline failed: {e}")
        logger.exception("Delete pipeline failed: kb=%s key=%s", kb_id, doc_source)
        raise
