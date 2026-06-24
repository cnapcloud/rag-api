"""meta Op — document state transitions backed by Postgres."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from infra.postgres import update_doc_fields
from pipeline.ops.upsert import UpsertResult

logger = logging.getLogger(__name__)


def update_meta(
    doc_id: str,
    upsert_result: UpsertResult,
    run_id: str = "",
    doc_type: str = "",
    embedding_model: str = "",
    doc_created_at: str = "",
) -> None:
    """Update document to status=indexed after a successful ingest."""
    fields: dict = {
        "status": "indexed",
        "chunk_count": upsert_result.chunk_count,
        "run_id": run_id,
        "error": None,
        "process_finished_at": datetime.now(timezone.utc).isoformat(),
    }
    if doc_type:
        fields["doc_type"] = doc_type
    if embedding_model:
        fields["embedding_model"] = embedding_model
    if doc_created_at:
        fields["doc_created_at"] = doc_created_at
    update_doc_fields(doc_id, fields)
    logger.info("Meta updated: doc_id=%s status=indexed chunks=%d", doc_id, upsert_result.chunk_count)


def set_pending(doc_id: str) -> None:
    update_doc_fields(doc_id, {"status": "pending"})
    logger.info("Status set to pending: doc_id=%s", doc_id)


def set_processing(doc_id: str, run_id: str = "") -> None:
    update_doc_fields(doc_id, {
        "status": "running",
        "run_id": run_id,
        "process_started_at": datetime.now(timezone.utc).isoformat(),
    })


def set_deleting(doc_id: str, run_id: str = "") -> None:
    update_doc_fields(doc_id, {"status": "deleting", "run_id": run_id})
    logger.info("Status set to deleting: doc_id=%s", doc_id)


def restore_indexed(doc_id: str) -> None:
    """Restore status to indexed after a skip (e.g. no-op re-index)."""
    update_doc_fields(doc_id, {"status": "indexed"})
    logger.info("Status restored to indexed (skip): doc_id=%s", doc_id)


def set_failed(doc_id: str, error: str, run_id: str = "") -> None:
    update_doc_fields(doc_id, {
        "status": "failed",
        "error": error[:500],
        "run_id": run_id,
        "process_finished_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.error("Pipeline failed: doc_id=%s error=%s", doc_id, error[:200])
