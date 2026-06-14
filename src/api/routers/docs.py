"""Document management router — upload, delete, status, reindex."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Query, UploadFile
from botocore.exceptions import ClientError

from exceptions import ConflictError, IngestValidationError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".md", ".docx", ".txt", ".hwp"}


def _check_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise IngestValidationError(f"Unsupported file format: {ext}")
    return ext


def _trigger_ingest(kb_id: str, object_key: str, etag: str, file_size: int, force: bool = False) -> None:
    from dagster_pipeline.sensors.event_queue_sensor import enqueue_upload_event

    enqueue_upload_event(kb_id=kb_id, object_key=object_key, etag=etag, file_size=file_size, force=force)


@router.post("/kb/{kb_id}/docs/upload", status_code=202)
async def upload_doc(kb_id: str, file: UploadFile = File(...)):
    """
    Single document upload: store in S3.
    Ingest is triggered by S3 event webhook (POST /internal/s3-event).
    """
    from infra.s3 import upload_object
    from infra.redis import list_kb_ids

    if kb_id not in list_kb_ids():
        raise NotFoundError(f"KB not found: {kb_id}")

    _check_ext(file.filename or "")
    content = await file.read()
    object_key = file.filename or f"upload_{uuid.uuid4()}"

    etag = upload_object(
        kb_id=kb_id,
        object_key=object_key,
        data=content,
        content_type=file.content_type or "application/octet-stream",
    )

    return {
        "object_key": object_key,
        "status_url": f"/api/kb/{kb_id}/docs/{object_key}/status",
        "etag": etag,
    }


@router.post("/kb/{kb_id}/docs/upload/batch", status_code=202)
async def upload_docs_batch(
    kb_id: str,
    files: list[UploadFile] = File(...),
):
    """
    Batch upload: store files in S3.
    Ingest is triggered by S3 event webhook (POST /internal/s3-event).
    """
    from infra.s3 import upload_object
    from infra.redis import list_kb_ids

    if kb_id not in list_kb_ids():
        raise NotFoundError(f"KB not found: {kb_id}")

    results = []
    for file in files:
        try:
            _check_ext(file.filename or "")
            content = await file.read()
            object_key = file.filename or f"upload_{uuid.uuid4()}"
            etag = upload_object(
                kb_id=kb_id,
                object_key=object_key,
                data=content,
                content_type=file.content_type or "application/octet-stream",
            )
            results.append(
                {
                    "filename": object_key,
                    "status_url": f"/api/kb/{kb_id}/docs/{object_key}/status",
                    "etag": etag,
                }
            )
        except (IngestValidationError, ClientError) as e:
            results.append({"filename": file.filename, "error": str(e), "status": "error"})

    return {"results": results}


@router.get("/kb/{kb_id}/docs")
async def list_docs(
    kb_id: str,
    status: str | None = Query(default=None),
):
    from infra.redis import list_docs as redis_list_docs
    from infra.redis import list_docs_by_status

    if status:
        docs = list_docs_by_status(kb_id, status)
    else:
        docs = redis_list_docs(kb_id)
    return {"kb_id": kb_id, "docs": docs, "total": len(docs)}


@router.get("/kb/{kb_id}/docs/{key:path}/status")
async def get_doc_status(kb_id: str, key: str):
    from infra.redis import get_doc_status

    data = get_doc_status(kb_id, key)
    if not data:
        raise NotFoundError(f"Document not found: kb={kb_id} key={key}")
    return {"kb_id": kb_id, "object_key": key, **data}


@router.delete("/kb/{kb_id}/docs/{key:path}", status_code=200)
async def delete_doc(kb_id: str, key: str):
    from infra.s3 import delete_object
    from infra.qdrant import delete_chunks_by_doc
    from infra.redis import delete_doc_meta

    delete_chunks_by_doc(kb_id, key)
    delete_doc_meta(kb_id, key)

    # S3 delete is best-effort: Qdrant/Redis cleanup already succeeded.
    try:
        delete_object(kb_id, key)
    except ClientError as e:
        logger.warning("S3 object deletion failed (ignored): kb=%s key=%s err=%s", kb_id, key, e)

    return {"kb_id": kb_id, "object_key": key, "status": "deleted"}


@router.post("/kb/{kb_id}/reindex", status_code=202)
async def reindex_kb(
    kb_id: str,
    force: bool = Query(False),
):
    """
    Re-index all documents in a KB.
    Compares S3 ETag vs Redis ETag and queues changed documents.
    With force=true, skips ETag comparison and re-indexes everything.
    Returns: { queued: N, skipped: M }
    """
    from infra.s3 import list_kb_objects
    from infra.redis import get_doc_etag

    objects = list_kb_objects(kb_id)
    queued = 0
    skipped = 0

    for object_key, s3_etag in objects:
        if not force:
            redis_etag = get_doc_etag(kb_id, object_key)
            if redis_etag == s3_etag:
                skipped += 1
                continue

        _trigger_ingest(kb_id, object_key, s3_etag, 0, force=force)
        queued += 1

    logger.info("Reindex KB: kb=%s queued=%d skipped=%d force=%s", kb_id, queued, skipped, force)
    return {"kb_id": kb_id, "queued": queued, "skipped": skipped}


@router.post("/kb/{kb_id}/docs/reindex", status_code=202)
async def reindex_doc(
    kb_id: str,
    key: str = Query(..., description="Object key (may contain /)"),
    force: bool = Query(False),
):
    """
    Re-index a single document.
    Compares S3 ETag vs Redis ETag; skips if unchanged unless force=true.
    Returns: { queued: N, skipped: M }
    """
    from infra.s3 import get_object_etag
    from infra.redis import get_doc_etag

    s3_etag = get_object_etag(kb_id, key)
    if s3_etag is None:
        raise NotFoundError(f"Document not found in S3: kb={kb_id} key={key}")

    if not force:
        redis_etag = get_doc_etag(kb_id, key)
        if redis_etag == s3_etag:
            return {"kb_id": kb_id, "queued": 0, "skipped": 1}

    _trigger_ingest(kb_id, key, s3_etag, 0, force=force)
    logger.info("Reindex doc: kb=%s key=%s force=%s", kb_id, key, force)
    return {"kb_id": kb_id, "queued": 1, "skipped": 0}


@router.post("/kb/{kb_id}/docs/{key:path}/recover", status_code=202)
async def recover_doc(kb_id: str, key: str):
    """Force-recover a stuck document by resetting status=running to failed and re-queuing."""
    import json

    from infra.redis import get_doc_status, get_redis_client
    from pipeline.ops.meta import set_failed  # noqa: PLC0415

    data = get_doc_status(kb_id, key)
    if not data:
        raise NotFoundError(f"Document not found: kb={kb_id} key={key}")
    if data.get("status") != "running":
        raise ConflictError(
            f"Document is not in a recoverable state: status={data.get('status')}"
        )
    set_failed(kb_id, key, "Manually recovered via API", run_id=data.get("run_id", ""))
    event = json.dumps({"kb_id": kb_id, "object_key": key, "etag": data.get("etag", ""), "force": True})
    get_redis_client().lpush("rag:upload:queue", event)
    logger.info("Manual recover queued: kb=%s key=%s", kb_id, key)
    return {"kb_id": kb_id, "object_key": key, "queued": True}


@router.get("/docs/status")
async def all_docs_status():
    from infra.redis import list_docs as redis_list_docs
    from infra.redis import list_kb_ids

    kb_ids = list_kb_ids()
    all_docs = {}
    for kb_id in kb_ids:
        all_docs[kb_id] = redis_list_docs(kb_id)
    return {"knowledge_bases": all_docs}
