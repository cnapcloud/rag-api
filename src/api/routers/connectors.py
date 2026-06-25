"""Connector CRUD and sync trigger endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, model_validator

from exceptions import ConfigError, ConflictError, NotFoundError

logger = logging.getLogger(__name__)
router = APIRouter()

_STALE_SYNC_TIMEOUT_SEC = 1800  # 30 minutes
_INDEXING_POLL_INTERVAL_SEC = 5
_INDEXING_TIMEOUT_SEC = 1800  # 30 minutes


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
        return self


class ConnectorPatch(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    sync_schedule: str | None = None
    schedule_enabled: bool | None = None
    status: Literal["active", "paused"] | None = None


@router.post("", status_code=201)
async def create_connector(body: ConnectorCreate):
    import psycopg.errors

    from infra.postgres import create_connector as pg_create, get_kb_meta

    if get_kb_meta(body.kb_id) is None:
        raise NotFoundError(f"KB not found: {body.kb_id}")

    try:
        return pg_create(
            kb_id=body.kb_id,
            name=body.name,
            source_type=body.source_type,
            config=body.config,
            sync_schedule=body.sync_schedule,
            schedule_enabled=body.schedule_enabled,
        )
    except psycopg.errors.UniqueViolation as e:
        raise ConflictError(f"Connector already exists in KB: {body.kb_id}") from e


@router.get("")
async def list_connectors_endpoint(
    kb_id: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="created_at"),
    sort_order: str = Query(default="desc"),
):
    from infra.postgres import list_connectors

    return {"items": list_connectors(
        kb_id=kb_id,
        source_type=source_type,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )}


@router.get("/{connector_id}")
async def get_connector_endpoint(connector_id: str):
    from infra.postgres import get_connector

    connector = get_connector(connector_id)
    if connector is None:
        raise NotFoundError(f"Connector not found: {connector_id}")
    return connector


@router.patch("/{connector_id}")
async def patch_connector(connector_id: str, body: ConnectorPatch):
    from infra.postgres import get_connector, update_connector

    if get_connector(connector_id) is None:
        raise NotFoundError(f"Connector not found: {connector_id}")

    fields = body.model_dump(exclude_unset=True)
    updated = update_connector(connector_id, fields)
    return updated


@router.delete("/{connector_id}", status_code=202)
async def delete_connector_endpoint(connector_id: str, background_tasks: BackgroundTasks):
    from infra.postgres import get_connector, set_connector_status

    if get_connector(connector_id) is None:
        raise NotFoundError(f"Connector not found: {connector_id}")

    set_connector_status(connector_id, "deleting")
    background_tasks.add_task(_cascade_delete, connector_id)
    return {"connector_id": connector_id, "status": "deleting"}


def _cascade_delete(connector_id: str) -> None:
    from botocore.exceptions import ClientError as S3ClientError

    from infra.postgres import (
        delete_connector,
        list_docs_by_connector,
        soft_delete_doc,
    )
    from infra.qdrant import delete_chunks_by_doc_id
    from infra.s3 import delete_by_key

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
    from infra.postgres import get_connector, set_connector_sync_status

    connector = get_connector(connector_id)
    if connector is None:
        raise NotFoundError(f"Connector not found: {connector_id}")

    if connector["status"] == "paused":
        raise ConflictError(f"Connector is paused: {connector_id}")

    if connector["sync_status"] == "running":
        sync_started_at_str = connector.get("sync_started_at")
        if sync_started_at_str:
            started_at = datetime.fromisoformat(sync_started_at_str).astimezone(timezone.utc)
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            if elapsed < _STALE_SYNC_TIMEOUT_SEC:
                raise ConflictError(f"Sync already in progress: {connector_id}")
            logger.warning(
                "Stale sync lock detected, proceeding: connector_id=%s elapsed=%ds",
                connector_id, int(elapsed),
            )

    set_connector_sync_status(connector_id, "running")
    background_tasks.add_task(_run_sync, connector)
    return {"connector_id": connector_id, "sync_status": "running"}


def _wait_for_indexing(connector_id: str) -> None:
    """Poll Postgres until all docs for this connector reach a terminal status."""
    import time

    from infra.postgres import get_pending_doc_count_for_connector

    deadline = time.monotonic() + _INDEXING_TIMEOUT_SEC
    while time.monotonic() < deadline:
        pending = get_pending_doc_count_for_connector(connector_id)
        if pending == 0:
            return
        logger.debug("Waiting for indexing: connector_id=%s pending=%d", connector_id, pending)
        time.sleep(_INDEXING_POLL_INTERVAL_SEC)

    logger.warning("Indexing wait timed out: connector_id=%s", connector_id)


def _run_sync(connector: dict) -> None:
    from infra.postgres import set_connector_status, set_connector_sync_status

    connector_id = connector["connector_id"]
    try:
        _dispatch_sync(connector)
        _wait_for_indexing(connector_id)
        set_connector_sync_status(connector_id, "idle", last_synced_at=datetime.now(timezone.utc))
        logger.info("Connector sync complete: connector_id=%s", connector_id)
    except Exception as e:
        set_connector_status(connector_id, "error")
        set_connector_sync_status(connector_id, "idle")
        logger.error("Connector sync failed: connector_id=%s err=%s", connector_id, e)


def _dispatch_sync(connector: dict) -> None:
    source_type = connector["source_type"]
    if source_type == "web":
        from connectors.web import WebConnector

        WebConnector(connector.get("config") or {}).sync(
            connector["kb_id"], connector["connector_id"]
        )
    else:
        logger.info("Sync skipped: connector type not yet implemented: connector_id=%s source_type=%s", connector["connector_id"], source_type)


@router.post("/{connector_id}/sync/reset", status_code=200)
async def reset_sync_status(connector_id: str):
    from infra.postgres import get_connector, set_connector_sync_status

    connector = get_connector(connector_id)
    if connector is None:
        raise NotFoundError(f"Connector not found: {connector_id}")

    set_connector_sync_status(connector_id, "idle")
    logger.warning("Sync status manually reset to idle: connector_id=%s", connector_id)
    return {"connector_id": connector_id, "sync_status": "idle"}


@router.get("/{connector_id}/sync/status")
async def get_sync_status(connector_id: str):
    from infra.postgres import get_connector, get_connector_doc_counts

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
    from infra.postgres import get_connector, list_docs_by_connector_paginated

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
