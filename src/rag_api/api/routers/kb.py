"""KB management router — GET/POST/DELETE /api/kb."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from rag_api.exceptions import ConflictError, NotFoundError
from rag_api.tracing.span import rest_span

logger = logging.getLogger(__name__)

router = APIRouter()


class KBCreateRequest(BaseModel):
    kb_id: str
    kb_name: str = ""
    description: str | None = None
    tags: list[str] = []


class KBUpdateRequest(BaseModel):
    kb_name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class KBSettingsOverrideRequest(BaseModel):
    # dot-key -> value, e.g. {"ingestion.max_file_size_mb": 50, "chunking.chunk_size": 512}
    overrides: dict[str, Any]


@router.get("/kb")
@rest_span
async def list_kbs_endpoint(
    sort_by: str = Query(default="kb_id"),
    sort_order: str = Query(default="asc"),
):
    from rag_api.infra.postgres import list_kbs

    return {"knowledge_bases": list_kbs(sort_by=sort_by, sort_order=sort_order)}


@router.get("/kb/{kb_id}")
@rest_span
async def get_kb(kb_id: str):
    from rag_api.infra.postgres import get_kb_meta

    meta = get_kb_meta(kb_id)
    if meta is None:
        raise NotFoundError(f"KB not found: {kb_id}")
    return meta


@router.post("/kb", status_code=201)
@rest_span
async def create_kb(req: KBCreateRequest):
    from rag_api.infra.postgres import list_kb_ids, register_kb
    from rag_api.infra.qdrant import ensure_collection

    if req.kb_id in list_kb_ids():
        raise ConflictError(f"KB already exists: {req.kb_id}")

    register_kb(req.kb_id, req.kb_name, req.description, req.tags)
    ensure_collection(req.kb_id)

    return {"kb_id": req.kb_id, "status": "created"}


@router.patch("/kb/{kb_id}", status_code=200)
@rest_span
async def update_kb(kb_id: str, req: KBUpdateRequest):
    from rag_api.infra.postgres import get_kb_meta, update_kb_meta

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    update_kb_meta(kb_id, req.kb_name, req.description, req.tags)
    return {"kb_id": kb_id, "status": "updated"}


@router.delete("/kb/{kb_id}", status_code=200)
@rest_span
async def delete_kb(kb_id: str):
    """
    KB deletion order:
    1. Reject if any connector under this KB has a sync in progress
    2. Mark status = deleting
    3. Abort any pending/running ingest for docs in this KB (terminate Dagster runs,
       clear queued events) so no in-flight pipeline touches content we're about to purge
    4. Drop Qdrant collection
    5. Delete S3 prefix
    6. Delete Postgres metadata (cascades to connectors and documents)
    7. Reload Dagster workspace if any deleted connector had a schedule
    """
    from rag_api.infra.postgres import (
        delete_kb_meta,
        get_active_ingest_docs_for_kb,
        get_kb_meta,
        list_connectors,
        update_kb_status,
    )
    from rag_api.infra.qdrant import drop_collection
    from rag_api.infra.s3 import delete_kb_prefix
    from rag_api.pipeline.utils.abort_ingest import abort_active_ingest

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    connectors = list_connectors(kb_id=kb_id)
    running = [c["connector_id"] for c in connectors if c.get("sync_status") == "running"]
    if running:
        raise ConflictError(
            f"Cannot delete KB while connector sync is running: kb_id={kb_id} connectors={running}"
        )

    update_kb_status(kb_id, "deleting")

    had_schedule = any(c.get("sync_schedule") is not None for c in connectors)

    abort_active_ingest(get_active_ingest_docs_for_kb(kb_id))

    drop_collection(kb_id)
    deleted_count = delete_kb_prefix(kb_id)
    delete_kb_meta(kb_id)

    if had_schedule:
        from rag_api.infra.dagster_utils import reload_code_location
        reload_code_location()

    return {"kb_id": kb_id, "status": "deleted", "s3_objects_deleted": deleted_count}


def _validate_overrides(overrides: dict[str, Any]) -> None:
    """Allow-list + override-metadata + field-path check for every key, then value-range check —
    see docs/internal/design/kb-settings-override.md §9.1 and
    kb-settings-override-schema.md §4. Must run before any write."""
    from rag_api.config.settings import (
        get_settings,
        validate_override_key,
        validate_override_values,
    )

    settings = get_settings()
    settings_cls = type(settings)
    for key in overrides:
        validate_override_key(settings_cls, key)
    # PATCH treats a null value as "clear this override" (see KBSettingsOverrideRequest), not an
    # actual field value — skip those, no typed field in Settings ever accepts None.
    non_null_overrides = {k: v for k, v in overrides.items() if v is not None}
    validate_override_values(settings, non_null_overrides)


@router.get("/kb/{kb_id}/settings")
@rest_span
async def get_kb_effective_settings(kb_id: str):
    """Effective settings (global + KB override merged) — ingestion/chunking/dedup/retrieval only.

    Never returns the full Settings object: it also holds provider/redis/postgres/qdrant
    credentials that must not leak through a KB-scoped read endpoint. retrieval.rerank.api_key
    is excluded even though the rest of `retrieval` is included (deny-listed via
    json_schema_extra={"override": False}, docs/internal/design/parent-child-chunking.md §6).
    """
    from rag_api.config.settings import resolve_settings
    from rag_api.infra.postgres import get_kb_meta

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    cfg = resolve_settings(kb_id)
    retrieval = cfg.retrieval.model_dump()
    retrieval["rerank"].pop("api_key", None)
    return {
        "ingestion": cfg.ingestion.model_dump(),
        "chunking": cfg.chunking.model_dump(),
        "dedup": cfg.dedup.model_dump(),
        "retrieval": retrieval,
    }


@router.get("/kb/{kb_id}/settings/schema")
@rest_span
async def get_kb_settings_schema(kb_id: str):
    """dot-key별 type/enum/default/overridable/min/max/description/group — rag-admin이 폼을
    하드코딩 없이 동적으로 그리기 위한 스키마(kb-settings-override-schema.md §5).
    """
    from rag_api.config.settings import describe_overridable_settings, get_settings
    from rag_api.infra.postgres import get_kb_meta

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    return {"schema": describe_overridable_settings(get_settings())}


@router.get("/kb/{kb_id}/settings/overrides")
@rest_span
async def get_kb_settings_overrides_endpoint(kb_id: str):
    from rag_api.infra.postgres import get_kb_meta, get_kb_settings_overrides

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    return {"overrides": get_kb_settings_overrides(kb_id)}


@router.put("/kb/{kb_id}/settings/overrides", status_code=200)
@rest_span
async def replace_kb_settings_overrides_endpoint(kb_id: str, req: KBSettingsOverrideRequest):
    """Full replace — keys not present in the body are reset to the global value."""
    from rag_api.infra.postgres import get_kb_meta, replace_kb_settings_overrides

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    _validate_overrides(req.overrides)
    replace_kb_settings_overrides(kb_id, req.overrides)
    return {"kb_id": kb_id, "overrides": req.overrides}


@router.patch("/kb/{kb_id}/settings/overrides", status_code=200)
@rest_span
async def merge_kb_settings_overrides(kb_id: str, req: KBSettingsOverrideRequest):
    """Per-key upsert — a value of null clears that key (reset to global). Keys not present in
    the body are left untouched. Independent row writes, no read-modify-write race."""
    from rag_api.infra.postgres import (
        delete_kb_settings_override,
        get_kb_meta,
        get_kb_settings_overrides,
        upsert_kb_settings_override,
    )

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    _validate_overrides(req.overrides)
    for key, value in req.overrides.items():
        if value is None:
            delete_kb_settings_override(kb_id, key)
        else:
            upsert_kb_settings_override(kb_id, key, value)

    return {"kb_id": kb_id, "overrides": get_kb_settings_overrides(kb_id)}


@router.delete("/kb/{kb_id}/settings/overrides", status_code=200)
@rest_span
async def clear_kb_settings_overrides_endpoint(kb_id: str):
    from rag_api.infra.postgres import clear_kb_settings_overrides, get_kb_meta

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    clear_kb_settings_overrides(kb_id)
    return {"kb_id": kb_id, "status": "overrides_cleared"}
