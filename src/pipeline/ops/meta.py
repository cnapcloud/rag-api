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
        "updated_at": datetime.now(timezone.utc).isoformat(),
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
    """Set status=running at the start of an ingest operation."""
    redis_infra.set_doc_status(
        kb_id,
        object_key,
        {"status": "running", "etag": etag, "run_id": run_id, "updated_at": datetime.now(timezone.utc).isoformat()},
    )


def set_deleting(kb_id: str, object_key: str, run_id: str = "") -> None:
    """Set status=deleting at the start of a delete operation."""
    redis_infra.set_doc_status(kb_id, object_key, {"status": "deleting", "run_id": run_id, "updated_at": datetime.now(timezone.utc).isoformat()})
    logger.info("Status set to deleting: kb=%s key=%s", kb_id, object_key)




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
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    logger.error("Pipeline failed: kb=%s key=%s error=%s", kb_id, object_key, error[:200])