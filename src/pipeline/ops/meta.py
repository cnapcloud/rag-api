"""meta Op — document metadata state transitions (backed by Postgres)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from infra import postgres as postgres_infra
from pipeline.ops.upsert import UpsertResult

logger = logging.getLogger(__name__)


def update_meta(
    kb_id: str,
    doc_source: str,
    upsert_result: UpsertResult,
    etag: str = "",
    run_id: str = "",
    file_size: int = 0,
    doc_type: str = "",
    embedding_model: str = "",
    doc_created_at: str = "",
) -> None:
    """Update document status to indexed after a successful ingest."""
    fields: dict = {
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
    if doc_created_at:
        fields["doc_created_at"] = doc_created_at
    postgres_infra.set_doc_status(kb_id, doc_source, fields)
    logger.info("Meta updated: kb=%s key=%s status=indexed chunks=%d", kb_id, doc_source, upsert_result.chunk_count)


def set_pending(kb_id: str, doc_source: str) -> None:
    """Set status=pending when an ingest or delete event is enqueued and no active run exists."""
    postgres_infra.set_doc_status(
        kb_id,
        doc_source,
        {"status": "pending", "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    logger.info("Status set to pending: kb=%s key=%s", kb_id, doc_source)


def set_processing(kb_id: str, doc_source: str, run_id: str = "") -> None:
    """Set status=running at the start of an ingest operation."""
    postgres_infra.set_doc_status(
        kb_id,
        doc_source,
        {"status": "running", "run_id": run_id, "updated_at": datetime.now(timezone.utc).isoformat()},
    )


def set_deleting(kb_id: str, doc_source: str, run_id: str = "") -> None:
    """Set status=deleting at the start of a delete operation."""
    postgres_infra.set_doc_status(
        kb_id,
        doc_source,
        {"status": "deleting", "run_id": run_id, "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    logger.info("Status set to deleting: kb=%s key=%s", kb_id, doc_source)


def restore_indexed(kb_id: str, doc_source: str, etag: str = "") -> None:
    """Restore status to indexed after an ETag-skip (no-op ingest).

    Called when the dispatch layer set processing but validate found ETag unchanged.
    """
    fields: dict = {"status": "indexed"}
    if etag:
        fields["etag"] = etag
    postgres_infra.set_doc_status(kb_id, doc_source, fields)
    logger.info("Status restored to indexed (ETag skip): kb=%s key=%s", kb_id, doc_source)


def set_failed(kb_id: str, doc_source: str, error: str, run_id: str = "") -> None:
    """Set status=failed with error message."""
    postgres_infra.set_doc_status(
        kb_id,
        doc_source,
        {
            "status": "failed",
            "error": error[:500],
            "run_id": run_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    logger.error("Pipeline failed: kb=%s key=%s error=%s", kb_id, doc_source, error[:200])
