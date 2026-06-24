"""KB management router — GET/POST/DELETE /api/kb."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from exceptions import ConflictError, NotFoundError

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


@router.get("/kb")
async def list_kbs_endpoint(
    sort_by: str = Query(default="kb_id"),
    sort_order: str = Query(default="asc"),
):
    from infra.postgres import list_kbs

    return {"knowledge_bases": list_kbs(sort_by=sort_by, sort_order=sort_order)}


@router.get("/kb/{kb_id}")
async def get_kb(kb_id: str):
    from infra.postgres import get_kb_meta

    meta = get_kb_meta(kb_id)
    if meta is None:
        raise NotFoundError(f"KB not found: {kb_id}")
    return meta


@router.post("/kb", status_code=201)
async def create_kb(req: KBCreateRequest):
    from infra.postgres import list_kb_ids, register_kb
    from infra.qdrant import ensure_collection

    if req.kb_id in list_kb_ids():
        raise ConflictError(f"KB already exists: {req.kb_id}")

    register_kb(req.kb_id, req.kb_name, req.description, req.tags)
    ensure_collection(req.kb_id)

    return {"kb_id": req.kb_id, "status": "created"}


@router.patch("/kb/{kb_id}", status_code=200)
async def update_kb(kb_id: str, req: KBUpdateRequest):
    from infra.postgres import get_kb_meta, update_kb_meta

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    update_kb_meta(kb_id, req.kb_name, req.description, req.tags)
    return {"kb_id": kb_id, "status": "updated"}


@router.delete("/kb/{kb_id}", status_code=200)
async def delete_kb(kb_id: str):
    """
    KB deletion order:
    1. Mark status = deleting
    2. Drop Qdrant collection
    3. Delete S3 prefix
    4. Delete Postgres metadata (cascades to documents)
    """
    from infra.postgres import delete_kb_meta, get_kb_meta, update_kb_status
    from infra.qdrant import drop_collection
    from infra.s3 import delete_kb_prefix

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")

    update_kb_status(kb_id, "deleting")

    drop_collection(kb_id)
    deleted_count = delete_kb_prefix(kb_id)
    delete_kb_meta(kb_id)

    return {"kb_id": kb_id, "status": "deleted", "s3_objects_deleted": deleted_count}
