"""Connector CRUD and sync trigger endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, model_validator

from rag_api.exceptions import ConflictError, NotFoundError

logger = logging.getLogger(__name__)
router = APIRouter()

_STALE_SYNC_TIMEOUT_SEC = 1800  # 30 minutes
_INDEXING_POLL_INTERVAL_SEC = 5
_INDEXING_TIMEOUT_SEC = 1800  # 30 minutes


_SOURCE_INT_FIELDS: dict[str, dict[str, tuple[int, int]]] = {
    "web": {
        "depth": (1, 10),
        "max_pages": (1, 500),
        "request_timeout_sec": (1, 300),
        "request_delay_ms": (0, 5000),
        "min_content_chars": (0, 10000),
    },
    "confluence": {
        "max_pages": (1, 500),
        "depth": (1, 10),
    },
}

_ALL_INT_FIELDS: dict[str, tuple[int, int]] = {
    field: bounds
    for fields in _SOURCE_INT_FIELDS.values()
    for field, bounds in fields.items()
}


def _validate_int_fields(config: dict, fields: dict[str, tuple[int, int]]) -> None:
    for field, (lo, hi) in fields.items():
        val = config.get(field)
        if val is None:
            continue
        if not isinstance(val, int) or isinstance(val, bool):
            raise ValueError(f"config.{field} must be an integer, got {type(val).__name__}")
        if not (lo <= val <= hi):
            raise ValueError(f"config.{field} must be between {lo} and {hi}, got {val}")


def _validate_cron(value: str | None, field: str = "sync_schedule") -> str | None:
    if value is None:
        return value
    from dagster._core.definitions.schedule_definition import is_valid_cron_schedule
    if not is_valid_cron_schedule(value):
        raise ValueError(f"Invalid cron expression for {field}: '{value}'")
    return value


class ConnectorCreate(BaseModel):
    kb_id: str
    name: str
    source_type: Literal["web", "confluence", "github"]
    config: dict[str, Any]
    sync_schedule: str | None = None
    schedule_enabled: bool = False

    @model_validator(mode="after")
    def validate_config(self) -> "ConnectorCreate":
        if self.source_type == "web":
            seed_urls = self.config.get("seed_urls")
            if not seed_urls:
                raise ValueError("config.seed_urls is required for source_type='web'")
        if self.source_type in _SOURCE_INT_FIELDS:
            _validate_int_fields(self.config, _SOURCE_INT_FIELDS[self.source_type])
        _validate_cron(self.sync_schedule)
        return self


class ConnectorPatch(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    sync_schedule: str | None = None
    schedule_enabled: bool | None = None
    status: Literal["active", "paused"] | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "ConnectorPatch":
        if self.config:
            _validate_int_fields(self.config, _ALL_INT_FIELDS)
        _validate_cron(self.sync_schedule)
        return self


@router.post("", status_code=201)
async def create_connector(body: ConnectorCreate, background_tasks: BackgroundTasks):
    import psycopg.errors

    from rag_api.infra.crypto import encrypt_config, mask_config
    from rag_api.infra.postgres import create_connector as pg_create, get_kb_meta

    if get_kb_meta(body.kb_id) is None:
        raise NotFoundError(f"KB not found: {body.kb_id}")

    try:
        connector = pg_create(
            kb_id=body.kb_id,
            name=body.name,
            source_type=body.source_type,
            config=encrypt_config(body.config),
            sync_schedule=body.sync_schedule,
            schedule_enabled=body.schedule_enabled,
        )
    except psycopg.errors.UniqueViolation as e:
        raise ConflictError(f"Connector already exists in KB: {body.kb_id}") from e

    if body.sync_schedule is not None:
        from rag_api.infra.dagster_utils import reload_code_location
        background_tasks.add_task(reload_code_location)

    return {**connector, "config": mask_config(connector.get("config") or {})}


@router.get("")
async def list_connectors_endpoint(
    kb_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
):
    from rag_api.infra.crypto import mask_config
    from rag_api.infra.postgres import list_connectors

    items = list_connectors(
        kb_id=kb_id,
        source_type=source_type,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {"items": [{**c, "config": mask_config(c.get("config") or {})} for c in items]}


@router.get("/{connector_id}")
async def get_connector_endpoint(connector_id: str):
    from rag_api.infra.crypto import mask_config
    from rag_api.infra.postgres import get_connector

    connector = get_connector(connector_id)
    if connector is None:
        raise NotFoundError(f"Connector not found: {connector_id}")
    return {**connector, "config": mask_config(connector.get("config") or {})}


@router.patch("/{connector_id}")
async def patch_connector(connector_id: str, body: ConnectorPatch, background_tasks: BackgroundTasks):
    from rag_api.infra.crypto import encrypt_config, mask_config
    from rag_api.infra.postgres import get_connector, update_connector

    if get_connector(connector_id) is None:
        raise NotFoundError(f"Connector not found: {connector_id}")

    fields = body.model_dump(exclude_unset=True)
    if "config" in fields and fields["config"]:
        fields["config"] = encrypt_config(fields["config"])
    updated = update_connector(connector_id, fields)

    if "sync_schedule" in fields:
        from rag_api.infra.dagster_utils import reload_code_location
        background_tasks.add_task(reload_code_location)

    return {**updated, "config": mask_config(updated.get("config") or {})}


@router.delete("/{connector_id}", status_code=202)
async def delete_connector_endpoint(connector_id: str, background_tasks: BackgroundTasks):
    from rag_api.infra.postgres import get_connector, set_connector_status

    connector = get_connector(connector_id)
    if connector is None:
        raise NotFoundError(f"Connector not found: {connector_id}")

    had_schedule = connector.get("sync_schedule") is not None
    set_connector_status(connector_id, "deleting")
    background_tasks.add_task(_cascade_delete, connector_id)
    if had_schedule:
        from rag_api.infra.dagster_utils import reload_code_location
        background_tasks.add_task(reload_code_location)
    return {"connector_id": connector_id, "status": "deleting"}


def _cascade_delete(connector_id: str) -> None:
    from botocore.exceptions import ClientError as S3ClientError

    from rag_api.infra.postgres import (
        delete_connector,
        list_docs_by_connector,
        soft_delete_doc,
    )
    from rag_api.infra.qdrant import delete_chunks_by_doc_id
    from rag_api.infra.s3 import delete_by_key

    docs = list_docs_by_connector(connector_id, include_deleted=False)
    for doc in docs:
        delete_chunks_by_doc_id(doc["kb_id"], doc["doc_id"])

        storage_key = doc.get("storage_key")
        if storage_key:
            try:
                delete_by_key(storage_key)
            except S3ClientError as e:
                logger.warning(
                    "S3 delete failed during connector cascade (ignored): connector_id=%s doc_id=%s err=%s",
                    connector_id, doc["doc_id"], e,
                )

        soft_delete_doc(doc["doc_id"])

    delete_connector(connector_id)
    logger.info("Connector cascade delete complete: connector_id=%s docs_deleted=%d", connector_id, len(docs))


@router.post("/{connector_id}/sync", status_code=202)
async def trigger_sync(connector_id: str, background_tasks: BackgroundTasks):
    from rag_api.infra.postgres import get_connector, set_connector_sync_status

    connector = get_connector(connector_id)
    if connector is None:
        raise NotFoundError(f"Connector not found: {connector_id}")

    if connector["status"] == "paused":
        raise ConflictError(f"Connector is paused: {connector_id}")

    if connector["sync_status"] == "running":
        raise ConflictError(f"Sync already in progress: {connector_id}")

    set_connector_sync_status(connector_id, "running")
    background_tasks.add_task(_run_sync, connector)
    return {"connector_id": connector_id, "sync_status": "running"}


def _wait_for_indexing(connector_id: str) -> None:
    """Poll Postgres until all docs for this connector reach a terminal status."""
    import time

    from rag_api.infra.postgres import get_pending_doc_count_for_connector

    deadline = time.monotonic() + _INDEXING_TIMEOUT_SEC
    while time.monotonic() < deadline:
        pending = get_pending_doc_count_for_connector(connector_id)
        if pending == 0:
            return
        logger.debug("Waiting for indexing: connector_id=%s pending=%d", connector_id, pending)
        time.sleep(_INDEXING_POLL_INTERVAL_SEC)

    logger.warning("Indexing wait timed out: connector_id=%s", connector_id)


def _run_sync(connector: dict) -> None:
    from rag_api.connectors.abort import clear_abort, is_abort_requested
    from rag_api.infra.postgres import set_connector_status, set_connector_sync_status

    connector_id = connector["connector_id"]
    try:
        _dispatch_sync(connector)
        if is_abort_requested(connector_id):
            logger.info("Connector sync aborted: connector_id=%s", connector_id)
        else:
            _wait_for_indexing(connector_id)
            logger.info("Connector sync complete: connector_id=%s", connector_id)
        set_connector_sync_status(connector_id, "idle", last_synced_at=datetime.now(timezone.utc))
    except Exception as e:
        if is_abort_requested(connector_id):
            logger.info("Connector sync interrupted by abort: connector_id=%s err=%s", connector_id, e)
        else:
            set_connector_status(connector_id, "error")
            logger.error("Connector sync failed: connector_id=%s err=%s", connector_id, e)
        set_connector_sync_status(connector_id, "idle")
    finally:
        clear_abort(connector_id)


def _dispatch_sync(connector: dict) -> None:
    from rag_api.infra.crypto import decrypt_config

    source_type = connector["source_type"]
    config = decrypt_config(connector.get("config") or {})

    if source_type == "web":
        from rag_api.connectors.web import WebConnector

        WebConnector(config).sync(connector["kb_id"], connector["connector_id"])
    elif source_type == "confluence":
        from rag_api.connectors.confluence import ConfluenceConnector

        ConfluenceConnector(config).sync(connector["kb_id"], connector["connector_id"])
    elif source_type == "github":
        from rag_api.connectors.github import GitHubConnector

        GitHubConnector(config).sync(connector["kb_id"], connector["connector_id"])
    else:
        logger.info(
            "Sync skipped: connector type not yet implemented: connector_id=%s source_type=%s",
            connector["connector_id"],
            source_type,
        )


@router.post("/{connector_id}/sync/abort", status_code=202)
async def abort_sync(connector_id: str):
    from rag_api.connectors.abort import request_abort
    from rag_api.infra.dagster_utils import terminate_dagster_run
    from rag_api.infra.postgres import get_active_ingest_docs_for_connector, get_connector, set_connector_sync_status
    from rag_api.pipeline.queue.enqueue import dequeue_upload_events
    from rag_api.pipeline.utils.doc_state import set_failed

    connector = get_connector(connector_id)
    if connector is None:
        raise NotFoundError(f"Connector not found: {connector_id}")
    if connector["sync_status"] != "running":
        raise ConflictError(f"No sync in progress: {connector_id}")

    request_abort(connector_id)
    set_connector_sync_status(connector_id, "idle")

    docs = get_active_ingest_docs_for_connector(connector_id)

    pending_ids = [d["doc_id"] for d in docs if d["status"] == "pending"]
    for doc_id in pending_ids:
        dequeue_upload_events(doc_id)
        set_failed(doc_id, "Aborted")

    run_ids = {d["run_id"] for d in docs if d["status"] == "running" and d.get("run_id")}
    for doc_id in [d["doc_id"] for d in docs if d["status"] == "running"]:
        set_failed(doc_id, "Aborted")
    for run_id in run_ids:
        try:
            terminate_dagster_run(run_id)
        except RuntimeError as e:
            logger.warning("Dagster terminate failed (ignored): run_id=%s err=%s", run_id, e)

    logger.info(
        "Sync aborted: connector_id=%s pending_cleared=%d runs_terminated=%d",
        connector_id, len(pending_ids), len(run_ids),
    )
    return {"connector_id": connector_id, "status": "abort_requested"}



@router.get("/{connector_id}/sync/status")
async def get_sync_status(connector_id: str):
    from rag_api.infra.postgres import get_connector, get_connector_doc_counts

    connector = get_connector(connector_id)
    if connector is None:
        raise NotFoundError(f"Connector not found: {connector_id}")

    return {
        "connector_id": connector_id,
        "status": connector["status"],
        "sync_status": connector["sync_status"],
        "sync_started_at": connector.get("sync_started_at"),
        "last_synced_at": connector.get("last_synced_at"),
        "doc_counts": get_connector_doc_counts(connector_id),
    }


@router.get("/{connector_id}/docs")
async def list_connector_docs(
    connector_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="updated_at"),
    sort_order: str = Query(default="desc"),
):
    from rag_api.infra.postgres import get_connector, list_docs_by_connector_paginated

    if get_connector(connector_id) is None:
        raise NotFoundError(f"Connector not found: {connector_id}")

    clamped_size = min(page_size, 100)
    items, total = list_docs_by_connector_paginated(
        connector_id=connector_id,
        page=page,
        page_size=clamped_size,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {"items": items, "total": total, "page": page, "page_size": clamped_size}
