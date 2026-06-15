"""pipeline/runner.py — Dagster 없이 단일 문서 파이프라인을 직접 실행."""

from __future__ import annotations

import logging

from config.settings import get_settings

logger = logging.getLogger(__name__)


def run_ingest_pipeline(
    kb_id: str,
    object_key: str,
    etag: str = "",
    file_size: int = 0,
    force: bool = False,
    run_id: str = "direct",
) -> int:
    """Run ingest pipeline from an S3 object key (downloads from S3 internally)."""
    from exceptions import IngestValidationError
    from infra import redis as redis_infra
    from pipeline.ops.chunk import chunk
    from pipeline.ops.embed import embed
    from pipeline.ops.meta import set_failed, set_processing, update_meta
    from pipeline.ops.parse import parse
    from pipeline.ops.upsert import upsert
    from pipeline.ops.validate import validate

    try:
        should_process = validate(kb_id, object_key, etag, file_size, force=force)
    except IngestValidationError as e:
        set_failed(kb_id, object_key, str(e), run_id=run_id)
        logger.error("Validation failed: kb=%s key=%s err=%s", kb_id, object_key, e)
        raise

    if not should_process:
        # If dispatch layer (QueueWorker) already set processing, restore to indexed.
        current = redis_infra.get_doc_status(kb_id, object_key)
        if current and current.get("status") == "running":
            from pipeline.ops.meta import restore_indexed
            restore_indexed(kb_id, object_key, etag=etag)
        logger.info("Skipping: kb=%s key=%s", kb_id, object_key)
        return 0

    set_processing(kb_id, object_key, etag=etag, run_id=run_id)

    try:
        documents = parse(kb_id=kb_id, object_key=object_key)
        nodes = chunk(documents)
        embedded_nodes = embed(nodes)
        upsert_result = upsert(kb_id, object_key, embedded_nodes)

        cfg = get_settings().embedding
        update_meta(
            kb_id=kb_id,
            object_key=object_key,
            upsert_result=upsert_result,
            etag=etag,
            run_id=run_id,
            file_size=file_size,
            doc_type=object_key.rsplit(".", 1)[-1],
            embedding_model=cfg.model,
        )
        logger.info("Ingest done: kb=%s key=%s chunks=%d", kb_id, object_key, upsert_result.chunk_count)
        return upsert_result.chunk_count

    except Exception as e:
        set_failed(kb_id, object_key, str(e), run_id=run_id)
        logger.exception("Pipeline failed: kb=%s key=%s", kb_id, object_key)
        raise


def run_delete_pipeline(kb_id: str, object_key: str) -> None:
    """단일 문서 삭제 파이프라인 직접 실행."""
    from infra import qdrant as qdrant_infra
    from infra import redis as redis_infra
    from pipeline.ops.meta import set_deleting, set_failed

    set_deleting(kb_id, object_key, run_id="direct")
    try:
        qdrant_infra.delete_chunks_by_doc(kb_id, object_key)
        redis_infra.delete_doc_meta(kb_id, object_key)
        logger.info("Delete done: kb=%s key=%s", kb_id, object_key)
    except Exception as e:
        set_failed(kb_id, object_key, f"delete_pipeline failed: {e}")
        logger.exception("Delete pipeline failed: kb=%s key=%s", kb_id, object_key)
        raise
