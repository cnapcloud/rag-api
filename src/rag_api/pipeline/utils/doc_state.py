"""pipeline/utils/doc_state.py — Single entry point for all document status transitions.

Only this module calls update_doc_fields with a "status" key.
All callers must import transition functions from here instead of calling
update_doc_fields directly with status fields.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import rag_api.infra.postgres as _pg

if TYPE_CHECKING:
    from rag_api.pipeline.ops.upsert import UpsertResult

logger = logging.getLogger(__name__)


def set_pending(doc_id: str, *, content_version: str | None = None) -> None:
    """Transition to pending. Clears last_error field."""
    fields: dict = {"status": "pending", "last_error": None}
    if content_version is not None:
        fields["content_version"] = content_version
    _pg.update_doc_fields(doc_id, fields)
    logger.info("Status set to pending: doc_id=%s", doc_id)


def set_uploading(doc_id: str, *, file_size: int, storage_key: str) -> None:
    """Transition to uploading — file transfer to S3 in progress."""
    _pg.update_doc_fields(doc_id, {"status": "uploading", "file_size": file_size, "storage_key": storage_key})
    logger.info("Status set to uploading: doc_id=%s", doc_id)


def set_fetching(doc_id: str, *, connector_id: str) -> None:
    """Transition to fetching — connector is downloading content."""
    _pg.update_doc_fields(doc_id, {"status": "fetching", "connector_id": connector_id})
    logger.info("Status set to fetching: doc_id=%s", doc_id)


def set_staged(
    doc_id: str,
    *,
    title: str,
    storage_key: str,
    content_version: str | None,
    file_size: int,
) -> None:
    """Transition to pending after connector stages content to S3. Clears last_error field."""
    _pg.update_doc_fields(doc_id, {
        "title": title,
        "status": "pending",
        "storage_key": storage_key,
        "content_version": content_version,
        "file_size": file_size,
        "last_error": None,
    })
    logger.info("Status set to pending (staged): doc_id=%s", doc_id)


def set_processing(doc_id: str, run_id: str = "") -> None:
    """Transition to running — pipeline has started."""
    _pg.update_doc_fields(doc_id, {
        "status": "running",
        "run_id": run_id,
        "process_started_at": datetime.now(UTC).isoformat(),
    })


def set_deleting(doc_id: str, run_id: str = "") -> None:
    """Transition to deleting — delete pipeline has started."""
    _pg.update_doc_fields(doc_id, {"status": "deleting", "run_id": run_id})
    logger.info("Status set to deleting: doc_id=%s", doc_id)


def set_indexed(
    doc_id: str,
    *,
    upsert_result: UpsertResult,
    run_id: str = "",
    doc_type: str = "",
    embedding_model: str = "",
) -> None:
    """Transition to indexed after successful ingest. Clears last_error field."""
    fields: dict = {
        "status": "indexed",
        "chunk_count": upsert_result.chunk_count,
        "run_id": run_id,
        "last_error": None,
        "process_finished_at": datetime.now(UTC).isoformat(),
    }
    if doc_type:
        fields["doc_type"] = doc_type
    if embedding_model:
        fields["embedding_model"] = embedding_model
    _pg.update_doc_fields(doc_id, fields)
    logger.info("Status set to indexed: doc_id=%s chunks=%d", doc_id, upsert_result.chunk_count)


def restore_indexed(doc_id: str) -> None:
    """Restore to indexed after a pipeline skip (e.g. dedup no-op). Clears last_error field."""
    _pg.update_doc_fields(doc_id, {"status": "indexed", "last_error": None})
    logger.info("Status restored to indexed (skip): doc_id=%s", doc_id)


def set_failed(doc_id: str, error: str, *, run_id: str = "") -> None:
    """Transition to failed — pipeline failure. Purges Qdrant/S3 artifacts."""
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.pipeline.utils.purge import purge_doc_artifacts

    doc = get_doc_by_id(doc_id)
    if doc:
        purge_doc_artifacts(doc_id, doc.get("kb_id", "") or "", swallow=True)

    _pg.update_doc_fields(doc_id, {
        "status": "failed",
        "last_error": error[:500],
        "run_id": run_id,
        "process_finished_at": datetime.now(UTC).isoformat(),
    })
    logger.error("Pipeline failed: doc_id=%s error=%s", doc_id, error[:200])


def set_fetch_failed(doc_id: str, error: str, *, connector_id: str | None = None) -> None:
    """Transition to failed — connector fetch failure. No artifact purge."""
    fields: dict = {"status": "failed", "last_error": error[:500]}
    if connector_id is not None:
        fields["connector_id"] = connector_id
    _pg.update_doc_fields(doc_id, fields)
    logger.warning("Fetch failed: doc_id=%s error=%s", doc_id, error[:200])


_STABLE_STATUSES = frozenset({"indexed", "failed", "deleted", "outdated"})


def is_active(status: str) -> bool:
    """Return True if the document is in an active processing state.

    Defined as the complement of stable statuses so that any new status added
    in the future is automatically treated as active (safe default).
    """
    return status not in _STABLE_STATUSES
