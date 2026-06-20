"""Document management router — upload, delete, status, reindex."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Literal

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


def _trigger_ingest(kb_id: str, doc_source: str, etag: str, file_size: int, force: bool = False) -> None:
    from pipeline.enqueue import enqueue_upload_event

    enqueue_upload_event(kb_id=kb_id, doc_source=doc_source, etag=etag, file_size=file_size, force=force)


@router.post("/kb/{kb_id}/docs/upload", status_code=202)
async def upload_doc(kb_id: str, file: UploadFile = File(...)):
    """
    Single document upload: store in S3.
    Ingest is triggered by S3 event webhook (POST /internal/s3-event).
    """
    from infra.postgres import list_kb_ids
    from infra.s3 import upload_object

    if kb_id not in list_kb_ids():
        raise NotFoundError(f"KB not found: {kb_id}")

    _check_ext(file.filename or "")
    content = await file.read()
    doc_source = file.filename or f"upload_{uuid.uuid4()}"

    etag = upload_object(
        kb_id=kb_id,
        doc_source=doc_source,
        data=content,
        content_type=file.content_type or "application/octet-stream",
    )

    return {
        "doc_source": doc_source,
        "status_url": f"/api/kb/{kb_id}/docs/{doc_source}/status",
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
    from infra.postgres import list_kb_ids
    from infra.s3 import upload_object

    if kb_id not in list_kb_ids():
        raise NotFoundError(f"KB not found: {kb_id}")

    results = []
    for file in files:
        try:
            _check_ext(file.filename or "")
            content = await file.read()
            doc_source = file.filename or f"upload_{uuid.uuid4()}"
            etag = upload_object(
                kb_id=kb_id,
                doc_source=doc_source,
                data=content,
                content_type=file.content_type or "application/octet-stream",
            )
            results.append(
                {
                    "doc_source": doc_source,
                    "status_url": f"/api/kb/{kb_id}/docs/{doc_source}/status",
                    "etag": etag,
                }
            )
        except (IngestValidationError, ClientError) as e:
            results.append({"doc_source": file.filename, "error": str(e), "status": "error"})

    return {"results": results}


_SORT_FIELDS = Literal["updated_at", "created_at", "doc_source", "chunk_count", "file_size"]
_SORT_ORDERS = Literal["asc", "desc"]


@router.get("/kb/{kb_id}/docs")
async def list_docs(
    kb_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: _SORT_FIELDS = Query(default="updated_at"),
    sort_order: _SORT_ORDERS = Query(default="desc"),
):
    from infra.postgres import list_docs_paginated

    clamped_size = min(page_size, 100)
    items, total = list_docs_paginated(
        kb_id=kb_id,
        page=page,
        page_size=clamped_size,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {"items": items, "total": total, "page": page, "page_size": clamped_size}


@router.get("/kb/{kb_id}/docs/{source:path}/status")
async def get_doc_status(kb_id: str, source: str):
    from infra.postgres import get_doc_status

    data = get_doc_status(kb_id, source)
    if not data:
        raise NotFoundError(f"Document not found: kb={kb_id} source={source}")
    return {"kb_id": kb_id, "doc_source": source, **data}


@router.delete("/kb/{kb_id}/docs/{source:path}", status_code=200)
async def delete_doc(kb_id: str, source: str):
    from infra.postgres import delete_doc_meta
    from infra.qdrant import delete_chunks_by_doc
    from infra.s3 import delete_object

    delete_chunks_by_doc(kb_id, source)
    delete_doc_meta(kb_id, source)

    # S3 delete is best-effort: Qdrant/Postgres cleanup already succeeded.
    try:
        delete_object(kb_id, source)
    except ClientError as e:
        logger.warning("S3 object deletion failed (ignored): kb=%s source=%s err=%s", kb_id, source, e)

    return {"kb_id": kb_id, "doc_source": source, "status": "deleted"}


@router.post("/kb/{kb_id}/reindex", status_code=202)
async def reindex_kb(
    kb_id: str,
    force: bool = Query(False),
):
    """
    Re-index all documents in a KB.
    Compares S3 ETag vs Postgres ETag and queues changed documents.
    With force=true, skips ETag comparison and re-indexes everything.
    Documents are enqueued oldest-first (doc_created_at from Postgres, fallback to S3 LastModified).
    Returns: { queued: N, skipped: M }
    """
    from infra.postgres import get_doc_etag
    from infra.postgres import list_docs as pg_list_docs
    from infra.s3 import list_kb_objects

    objects = list_kb_objects(kb_id)

    # Pre-fetch all Postgres doc metadata for sorting (one pass)
    pg_docs = {d["doc_source"]: d for d in pg_list_docs(kb_id)}

    # Determine which objects to queue, then sort oldest-first
    to_queue: list[tuple[str, str, str, int]] = []  # (doc_source, s3_etag, sort_key, file_size)
    skipped = 0

    for doc_source, s3_etag, s3_last_modified, file_size in objects:
        if not force:
            pg_etag = get_doc_etag(kb_id, doc_source)
            if pg_etag == s3_etag:
                skipped += 1
                continue
        sort_date = pg_docs.get(doc_source, {}).get("doc_created_at") or s3_last_modified
        to_queue.append((doc_source, s3_etag, sort_date, file_size))

    to_queue.sort(key=lambda x: x[2])

    for doc_source, s3_etag, _, file_size in to_queue:
        _trigger_ingest(kb_id, doc_source, s3_etag, file_size, force=force)

    queued = len(to_queue)
    logger.info("Reindex KB: kb=%s queued=%d skipped=%d force=%s", kb_id, queued, skipped, force)
    return {"kb_id": kb_id, "queued": queued, "skipped": skipped}


@router.post("/kb/{kb_id}/docs/reindex", status_code=202)
async def reindex_doc(
    kb_id: str,
    source: str = Query(..., description="Document source path (may contain /)"),
    force: bool = Query(False),
):
    """
    Re-index a single document.
    Compares S3 ETag vs Postgres ETag; skips if unchanged unless force=true.
    Returns: { queued: N, skipped: M }
    """
    from infra.postgres import get_doc_etag
    from infra.s3 import get_object_meta

    s3_etag, file_size = get_object_meta(kb_id, source)
    if s3_etag is None:
        raise NotFoundError(f"Document not found in S3: kb={kb_id} source={source}")

    if not force:
        pg_etag = get_doc_etag(kb_id, source)
        if pg_etag == s3_etag:
            return {"kb_id": kb_id, "queued": 0, "skipped": 1}

    _trigger_ingest(kb_id, source, s3_etag, file_size, force=force)
    logger.info("Reindex doc: kb=%s source=%s force=%s", kb_id, source, force)
    return {"kb_id": kb_id, "queued": 1, "skipped": 0}


@router.post("/kb/{kb_id}/docs/{source:path}/recover", status_code=202)
async def recover_doc(kb_id: str, source: str):
    """Force-recover a stuck document by resetting status=running to failed and re-queuing."""
    from pipeline.enqueue import enqueue_upload_event
    from infra.postgres import get_doc_status
    from pipeline.ops.meta import set_failed

    data = get_doc_status(kb_id, source)
    if not data:
        raise NotFoundError(f"Document not found: kb={kb_id} source={source}")
    if data.get("status") != "running":
        raise ConflictError(
            f"Document is not in a recoverable state: status={data.get('status')}"
        )
    set_failed(kb_id, source, "Manually recovered via API", run_id=data.get("run_id", ""))
    enqueue_upload_event(kb_id, source, etag=data.get("etag", ""), file_size=0, force=True)
    logger.info("Manual recover queued: kb=%s source=%s", kb_id, source)
    return {"kb_id": kb_id, "doc_source": source, "queued": True}


@router.get("/docs/status")
async def all_docs_status():
    from infra.postgres import list_docs as pg_list_docs
    from infra.postgres import list_kb_ids

    kb_ids = list_kb_ids()
    all_docs = {}
    for kb_id in kb_ids:
        all_docs[kb_id] = pg_list_docs(kb_id)
    return {"knowledge_bases": all_docs}
