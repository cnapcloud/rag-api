"""KB management router — GET/POST/DELETE /api/kb."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from exceptions import ConflictError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter()


class KBCreateRequest(BaseModel):
    kb_id: str
    description: str = ""


@router.get("/kb")
async def list_kbs():
    from infra.redis import get_redis_client, kb_meta_key, list_kb_ids

    r = get_redis_client()
    kb_ids = list_kb_ids(r)
    result = []
    for kb_id in sorted(kb_ids):
        meta = r.hgetall(kb_meta_key(kb_id))
        result.append({"kb_id": kb_id, "description": meta.get("description", "")})
    return {"knowledge_bases": result}


@router.post("/kb", status_code=201)
async def create_kb(req: KBCreateRequest):
    from infra.qdrant import ensure_collection
    from infra.redis import list_kb_ids, register_kb

    if req.kb_id in list_kb_ids():
        raise ConflictError(f"KB already exists: {req.kb_id}")

    register_kb(req.kb_id, req.description)
    ensure_collection(req.kb_id)

    return {"kb_id": req.kb_id, "status": "created"}


@router.delete("/kb/{kb_id}", status_code=200)
async def delete_kb(kb_id: str):
    """
    KB deletion order:
    1. Mark status = deleting
    2. Drop Qdrant collection
    3. Delete S3 prefix
    4. Delete Redis metadata
    """
    from infra.s3 import delete_kb_prefix
    from infra.qdrant import drop_collection
    from infra.redis import delete_kb_meta, get_redis_client, kb_meta_key

    r = get_redis_client()
    if not r.exists(kb_meta_key(kb_id)):
        raise NotFoundError(f"KB not found: {kb_id}")

    r.hset(kb_meta_key(kb_id), "status", "deleting")

    drop_collection(kb_id)
    deleted_count = delete_kb_prefix(kb_id)
    delete_kb_meta(kb_id)

    return {"kb_id": kb_id, "status": "deleted", "s3_objects_deleted": deleted_count}
