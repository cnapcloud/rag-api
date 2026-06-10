"""meta Op — Redis 문서 메타데이터 갱신."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from infra import redis as redis_infra
from pipeline.ops.upsert import UpsertResult

logger = logging.getLogger(__name__)


def update_meta(
    kb_id: str,
    object_key: str,
    upsert_result: UpsertResult,
    etag: str = "",
    run_id: str = "",
    file_size: int = 0,
    doc_type: str = "",
    embedding_model: str = "",
) -> None:
    """인덱싱 완료 후 Redis 문서 상태를 갱신한다."""
    fields = {
        "status": "indexed",
        "etag": etag,
        "chunk_count": upsert_result.chunk_count,
        "indexed_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "file_size": file_size,
        "doc_type": doc_type,
        "embedding_model": embedding_model,
        "error": "",
    }
    redis_infra.set_doc_status(kb_id, object_key, fields)
    if etag:
        redis_infra.set_doc_etag(kb_id, object_key, etag)
    logger.info("Meta updated: kb=%s key=%s status=indexed chunks=%d", kb_id, object_key, upsert_result.chunk_count)


def set_processing(kb_id: str, object_key: str, etag: str = "", run_id: str = "") -> None:
    """처리 시작 시 status=processing 설정."""
    redis_infra.set_doc_status(
        kb_id,
        object_key,
        {"status": "processing", "etag": etag, "run_id": run_id},
    )


def is_doc_busy(kb_id: str, object_key: str) -> bool:
    """Return True if the document has an in-progress operation (processing or deleting)."""
    status = redis_infra.get_doc_status(kb_id, object_key)
    return bool(status and status.get("status") in ("processing", "deleting"))


def set_deleting(kb_id: str, object_key: str, run_id: str = "") -> None:
    """Set status=deleting at the start of a delete operation."""
    redis_infra.set_doc_status(kb_id, object_key, {"status": "deleting", "run_id": run_id})
    logger.info("Status set to deleting: kb=%s key=%s", kb_id, object_key)


def try_set_processing(kb_id: str, object_key: str, etag: str = "", run_id: str = "") -> bool:
    """Check-and-set guard for upload dispatch (sensor / queue_worker).

    Returns False if the doc is busy (processing or deleting) — caller should delay.
    Returns True and sets processing if the doc is idle.
    """
    if is_doc_busy(kb_id, object_key):
        return False
    set_processing(kb_id, object_key, etag=etag, run_id=run_id)
    return True


def try_set_deleting(kb_id: str, object_key: str, run_id: str = "") -> bool:
    """Check-and-set guard for delete dispatch (sensor / queue_worker).

    Returns False if the doc is busy (processing or deleting) — caller should delay.
    Returns True and sets deleting if the doc is idle.
    """
    if is_doc_busy(kb_id, object_key):
        return False
    set_deleting(kb_id, object_key, run_id=run_id)
    return True


def restore_indexed(kb_id: str, object_key: str, etag: str = "") -> None:
    """Restore status to indexed after an ETag-skip (no-op ingest).

    Called when the dispatch layer set processing but validate found ETag unchanged.
    """
    redis_infra.set_doc_status(kb_id, object_key, {"status": "indexed"})
    if etag:
        redis_infra.set_doc_etag(kb_id, object_key, etag)
    logger.info("Status restored to indexed (ETag skip): kb=%s key=%s", kb_id, object_key)


def set_failed(kb_id: str, object_key: str, error: str, run_id: str = "") -> None:
    """실패 시 status=failed + error 메시지 설정."""
    redis_infra.set_doc_status(
        kb_id,
        object_key,
        {
            "status": "failed",
            "error": error[:500],  # Redis 저장 길이 제한
            "run_id": run_id,
        },
    )
    logger.error("Pipeline failed: kb=%s key=%s error=%s", kb_id, object_key, error[:200])