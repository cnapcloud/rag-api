"""Document management router — upload, delete, status, reindex."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from botocore.exceptions import ClientError
from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from rag_api.exceptions import ConflictError, IngestValidationError, NotFoundError
from rag_api.pipeline.steps.parse import supported_extensions
from rag_api.tracing.span import rest_span

logger = logging.getLogger(__name__)

router = APIRouter()


def _check_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in supported_extensions():
        raise IngestValidationError(f"Unsupported file format: {ext}")
    return ext


def _build_storage_key(kb_id: str, filename: str) -> str:
    return f"{kb_id}/{filename}"


@router.post("/kb/{kb_id}/docs/upload", status_code=202)
@rest_span
async def upload_doc(kb_id: str, file: UploadFile = File(...)):
    """Row-first single document upload.

    1. Create/update document row (status=uploading)
    2. Upload file to S3
    3. Update row with storage_key + content_version (ETag) + status=pending
    4. Enqueue ingest event
    """
    import psycopg.errors

    from rag_api.infra.postgres import create_doc, get_doc_by_source, list_kb_ids, update_doc_fields
    from rag_api.infra.s3 import upload_object
    from rag_api.pipeline.queue.enqueue import enqueue_upload_event
    from rag_api.pipeline.utils.doc_state import set_uploading
    from rag_api.pipeline.utils.source_uri import normalize_source_uri

    if kb_id not in list_kb_ids():
        raise NotFoundError(f"KB not found: {kb_id}")

    filename = file.filename or f"upload_{uuid.uuid4()}"
    _check_ext(filename)
    content = await file.read()
    file_size = len(content)

    source_uri = normalize_source_uri("s3", filename)
    storage_key = _build_storage_key(kb_id, filename)
    doc_type = Path(filename).suffix.lstrip(".").lower()

    existing = get_doc_by_source(kb_id, source_uri)
    if existing is None:
        try:
            doc = create_doc(
                kb_id=kb_id,
                source=source_uri,
                title=filename,
                source_type="s3",
                status="uploading",
                storage_key=storage_key,
                file_size=file_size,
                doc_type=doc_type,
                doc_created_at=datetime.now(UTC),
            )
        except psycopg.errors.UniqueViolation:
            # Race condition: concurrent upload created the row; retry lookup
            found = get_doc_by_source(kb_id, source_uri)
            if found is None:
                raise
            doc = found
            set_uploading(doc["doc_id"], file_size=file_size, storage_key=storage_key)
    else:
        from rag_api.pipeline.utils.doc_state import is_active
        ex_status = existing.get("status", "")
        if is_active(ex_status):
            logger.warning("Upload blocked — doc active: kb=%s doc_id=%s status=%s", kb_id, existing["doc_id"], ex_status)
            raise ConflictError(f"Document is active, try again later: doc_id={existing['doc_id']} status={ex_status}")
        doc = existing
        update_doc_fields(doc["doc_id"], {"status": "uploading", "file_size": file_size, "storage_key": storage_key})

    doc_id: str = doc["doc_id"]

    etag = upload_object(
        kb_id=kb_id,
        source=filename,
        data=content,
        content_type=file.content_type or "application/octet-stream",
    )

    update_doc_fields(doc_id, {"content_version": etag, "status": "pending"})
    enqueue_upload_event(doc_id=doc_id)

    return {
        "doc_id": doc_id,
        "source": source_uri,
        "etag": etag,
        "status_url": f"/api/kb/{kb_id}/docs/{doc_id}/status",
    }


@router.post("/kb/{kb_id}/docs/upload/batch", status_code=202)
@rest_span
async def upload_docs_batch(
    kb_id: str,
    files: list[UploadFile] = File(...),
):
    """Row-first batch document upload."""
    import psycopg.errors

    from rag_api.infra.postgres import create_doc, get_doc_by_source, list_kb_ids
    from rag_api.infra.s3 import upload_object
    from rag_api.pipeline.queue.enqueue import enqueue_upload_event
    from rag_api.pipeline.utils.doc_state import set_pending, set_uploading
    from rag_api.pipeline.utils.source_uri import normalize_source_uri

    if kb_id not in list_kb_ids():
        raise NotFoundError(f"KB not found: {kb_id}")

    results = []
    for file in files:
        try:
            filename = file.filename or f"upload_{uuid.uuid4()}"
            _check_ext(filename)
            content = await file.read()
            file_size = len(content)

            source_uri = normalize_source_uri("s3", filename)
            storage_key = _build_storage_key(kb_id, filename)
            doc_type = Path(filename).suffix.lstrip(".").lower()

            existing = get_doc_by_source(kb_id, source_uri)
            if existing is None:
                try:
                    doc = create_doc(
                        kb_id=kb_id,
                        source=source_uri,
                        title=filename,
                        source_type="s3",
                        status="uploading",
                        storage_key=storage_key,
                        file_size=file_size,
                        doc_type=doc_type,
                        doc_created_at=datetime.now(UTC),
                    )
                except psycopg.errors.UniqueViolation:
                    found = get_doc_by_source(kb_id, source_uri)
                    if found is None:
                        raise
                    doc = found
                    set_uploading(doc["doc_id"], file_size=file_size, storage_key=storage_key)
            else:
                from rag_api.pipeline.utils.doc_state import is_active
                ex_status = existing.get("status", "")
                if is_active(ex_status):
                    logger.warning(
                        "Upload blocked — doc active: kb=%s doc_id=%s status=%s",
                        kb_id, existing["doc_id"], ex_status,
                    )
                    raise ConflictError(
                        f"Document is active, try again later: doc_id={existing['doc_id']} status={ex_status}"
                    )
                doc = existing
                set_uploading(doc["doc_id"], file_size=file_size, storage_key=storage_key)

            doc_id: str = doc["doc_id"]

            etag = upload_object(
                kb_id=kb_id,
                source=filename,
                data=content,
                content_type=file.content_type or "application/octet-stream",
            )

            set_pending(doc_id, content_version=etag)
            enqueue_upload_event(doc_id=doc_id)

            results.append({
                "doc_id": doc_id,
                "source": source_uri,
                "etag": etag,
                "status_url": f"/api/kb/{kb_id}/docs/{doc_id}/status",
            })
        except (IngestValidationError, ClientError) as e:
            logger.warning(
                "Batch upload item rejected: kb=%s file=%s err=%s",
                kb_id, file.filename, e,
            )
            results.append({"title": file.filename or "unknown", "error": str(e), "status": "error"})

    return {"results": results}


_SORT_FIELDS = Literal["updated_at", "created_at", "title", "chunk_count", "file_size"]
_SORT_ORDERS = Literal["asc", "desc"]


@router.get("/kb/{kb_id}/docs")
@rest_span
async def list_docs(
    kb_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    status: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: _SORT_FIELDS = Query(default="updated_at"),
    sort_order: _SORT_ORDERS = Query(default="desc"),
):
    from rag_api.infra.postgres import list_docs_paginated

    clamped_size = min(page_size, 100)
    items, total = list_docs_paginated(
        kb_id=kb_id,
        page=page,
        page_size=clamped_size,
        status=status,
        source_type=source_type,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {"items": items, "total": total, "page": page, "page_size": clamped_size}


@router.get("/kb/{kb_id}/docs/status")
@rest_span
async def get_kb_doc_counts(kb_id: str):
    from rag_api.infra.postgres import get_kb_doc_counts as pg_get_kb_doc_counts
    from rag_api.infra.postgres import get_kb_meta

    if get_kb_meta(kb_id) is None:
        raise NotFoundError(f"KB not found: {kb_id}")
    return {"kb_id": kb_id, "doc_counts": pg_get_kb_doc_counts(kb_id)}


@router.get("/kb/{kb_id}/docs/{doc_id}/status")
@rest_span
async def get_doc_status(kb_id: str, doc_id: str):
    from rag_api.infra.postgres import get_doc_by_id

    doc = get_doc_by_id(doc_id)
    if doc is None or doc.get("kb_id") != kb_id:
        raise NotFoundError(f"Document not found: kb={kb_id} doc_id={doc_id}")
    return doc


@router.delete("/kb/{kb_id}/docs/{doc_id}", status_code=202)
@rest_span
async def delete_doc(kb_id: str, doc_id: str, force: bool = Query(False)):
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.pipeline.queue.enqueue import enqueue_delete_event
    from rag_api.pipeline.utils.doc_state import is_active

    doc = get_doc_by_id(doc_id)
    if doc is None or doc.get("kb_id") != kb_id:
        raise NotFoundError(f"Document not found: kb={kb_id} doc_id={doc_id}")

    status = doc.get("status", "")
    if is_active(status):
        logger.warning("Delete blocked — doc active: kb=%s doc_id=%s status=%s", kb_id, doc_id, status)
        raise ConflictError(f"Document is active, try again later: doc_id={doc_id} status={status}")

    enqueue_delete_event(doc_id, force=force)
    return {"kb_id": kb_id, "doc_id": doc_id, "status": "pending"}


@router.post("/kb/{kb_id}/reindex", status_code=202)
@rest_span
async def reindex_kb(
    kb_id: str,
    force: bool = Query(False),
):
    """Re-index all active documents in a KB.

    Compares current S3 ETag against content_version in Postgres.
    With force=true, re-indexes everything regardless of ETag match.
    Returns { queued: N, skipped: M }
    """
    from rag_api.infra.postgres import list_docs as pg_list_docs
    from rag_api.infra.s3 import get_object_meta
    from rag_api.pipeline.queue.enqueue import enqueue_upload_event
    from rag_api.pipeline.utils.doc_state import is_active

    docs = pg_list_docs(kb_id, include_deleted=False)
    queued = 0
    skipped = 0

    for doc in docs:
        doc_id = doc["doc_id"]
        status = doc.get("status", "")

        if status == "outdated":
            logger.debug("Reindex skipped — doc outdated: doc_id=%s", doc_id)
            skipped += 1
            continue

        if is_active(status):
            logger.debug("Reindex skipped — doc active: doc_id=%s status=%s", doc_id, status)
            skipped += 1
            continue

        storage_key = doc.get("storage_key") or ""
        if not storage_key:
            skipped += 1
            continue

        if not force:
            s3_etag, _ = get_object_meta(doc["kb_id"], storage_key.split("/", 1)[-1] if "/" in storage_key else storage_key)
            if s3_etag and s3_etag == doc.get("content_version"):
                skipped += 1
                continue

        enqueue_upload_event(doc_id=doc_id, force=force)
        queued += 1

    logger.info("Reindex KB: kb=%s queued=%d skipped=%d force=%s", kb_id, queued, skipped, force)
    return {"kb_id": kb_id, "queued": queued, "skipped": skipped}


@router.post("/kb/{kb_id}/docs/{doc_id}/reindex", status_code=202)
@rest_span
async def reindex_doc(
    kb_id: str,
    doc_id: str,
    force: bool = Query(False),
):
    """Re-index a single document by doc_id."""
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.infra.s3 import get_object_meta
    from rag_api.pipeline.queue.enqueue import enqueue_upload_event
    from rag_api.pipeline.utils.doc_state import is_active

    doc = get_doc_by_id(doc_id)
    if doc is None or doc.get("kb_id") != kb_id:
        raise NotFoundError(f"Document not found: kb={kb_id} doc_id={doc_id}")

    storage_key = doc.get("storage_key") or ""
    if not storage_key:
        raise NotFoundError(f"Document has no storage_key: doc_id={doc_id}")

    status = doc.get("status", "")
    if is_active(status):
        logger.warning("Reindex blocked — doc active: kb=%s doc_id=%s status=%s", kb_id, doc_id, status)
        raise ConflictError(f"Document is active, try again later: doc_id={doc_id} status={status}")

    if not force:
        source = storage_key.split("/", 1)[-1] if "/" in storage_key else storage_key
        s3_etag, _ = get_object_meta(kb_id, source)
        if s3_etag and s3_etag == doc.get("content_version"):
            return {"kb_id": kb_id, "doc_id": doc_id, "queued": 0, "skipped": 1}

    enqueue_upload_event(doc_id=doc_id, force=force)
    logger.info("Reindex doc: kb=%s doc_id=%s force=%s", kb_id, doc_id, force)
    return {"kb_id": kb_id, "doc_id": doc_id, "queued": 1, "skipped": 0}


@router.post("/kb/{kb_id}/docs/{doc_id}/fail", status_code=200)
@rest_span
async def force_fail_doc(
    kb_id: str,
    doc_id: str,
    reason: str = Query(default="Manually failed via API"),
):
    """Force-fail a document in uploading / pending / running / deleting state.

    If a Dagster run_id is present, the run is force-terminated first.
    Pending documents have their Redis queue events removed before failing.
    """
    from rag_api.infra.dagster_utils import terminate_dagster_run
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.pipeline.queue.enqueue import dequeue_upload_events
    from rag_api.pipeline.utils.doc_state import set_failed

    doc = get_doc_by_id(doc_id)
    if doc is None or doc.get("kb_id") != kb_id:
        raise NotFoundError(f"Document not found: kb={kb_id} doc_id={doc_id}")

    status = doc.get("status", "")
    if status not in ("uploading", "pending", "running", "deleting"):
        raise ConflictError(
            f"Cannot force-fail document in current state: status={status}"
        )

    run_id = doc.get("run_id") or ""
    if run_id:
        terminate_dagster_run(run_id)

    from rag_api.config.settings import get_settings
    worker_mode_active = get_settings().queue_worker.enabled and status in ("running", "deleting")
    if worker_mode_active:
        logger.warning(
            "Force fail set but background task cannot be terminated in queue_worker mode"
            " (task may still be running): doc_id=%s status_was=%s",
            doc_id,
            status,
        )

    dequeue_upload_events(doc_id)

    set_failed(doc_id, reason[:500], run_id=run_id)
    logger.info("Force fail applied: kb=%s doc_id=%s status_was=%s", kb_id, doc_id, status)

    response: dict = {"kb_id": kb_id, "doc_id": doc_id, "status": "failed"}
    if worker_mode_active:
        response["warning"] = (
            "Status set to failed, but the background task is still running"
            " and may overwrite this status (queue_worker mode has no terminate support)."
        )
    return response


@router.post("/kb/{kb_id}/docs/{doc_id}/recover", status_code=202)
@rest_span
async def recover_doc(kb_id: str, doc_id: str):
    """Force-recover a stuck document by resetting status=running to failed and re-queuing."""
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.pipeline.queue.enqueue import enqueue_upload_event
    from rag_api.pipeline.utils.doc_state import set_failed

    doc = get_doc_by_id(doc_id)
    if doc is None or doc.get("kb_id") != kb_id:
        raise NotFoundError(f"Document not found: kb={kb_id} doc_id={doc_id}")
    if doc.get("status") != "running":
        raise ConflictError(
            f"Document is not in a recoverable state: status={doc.get('status')}"
        )
    set_failed(doc_id, "Manually recovered via API", run_id=doc.get("run_id", ""))
    enqueue_upload_event(doc_id=doc_id, force=True)
    logger.info("Manual recover queued: kb=%s doc_id=%s", kb_id, doc_id)
    return {"kb_id": kb_id, "doc_id": doc_id, "queued": True}


@router.get("/docs")
@rest_span
async def list_all_docs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: _SORT_FIELDS = Query(default="updated_at"),
    sort_order: _SORT_ORDERS = Query(default="desc"),
):
    from rag_api.infra.postgres import list_all_docs_paginated

    clamped_size = min(page_size, 100)
    items, total = list_all_docs_paginated(
        page=page,
        page_size=clamped_size,
        status=status,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {"items": items, "total": total, "page": page, "page_size": clamped_size}


@router.get("/kb/{kb_id}/docs/{doc_id}/download")
@rest_span
async def download_doc(kb_id: str, doc_id: str):
    """Stream the raw file for a document from S3."""
    import mimetypes

    from rag_api.config.settings import get_settings
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.infra.s3 import get_s3_client

    doc = get_doc_by_id(doc_id)
    if doc is None or doc.get("kb_id") != kb_id:
        raise NotFoundError(f"Document not found: kb={kb_id} doc_id={doc_id}")

    storage_key = doc.get("storage_key") or ""
    if not storage_key:
        raise NotFoundError(f"Document has no stored file: doc_id={doc_id}")

    cfg = get_settings().s3
    client = get_s3_client()

    try:
        resp = client.get_object(Bucket=cfg.rag_bucket, Key=storage_key)
    except ClientError as e:
        raise NotFoundError(f"File not found in storage: {storage_key}") from e

    filename = Path(storage_key).name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    def _iter():
        yield from resp["Body"].iter_chunks(chunk_size=65536)

    logger.info("Download doc: kb=%s doc_id=%s key=%s", kb_id, doc_id, storage_key)
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii") or "download"
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        _iter(),
        media_type=content_type,
        headers={"Content-Disposition": disposition},
    )


@router.get("/docs/status")
@rest_span
async def all_docs_status():
    from rag_api.infra.postgres import get_kb_doc_counts as pg_get_kb_doc_counts
    from rag_api.infra.postgres import list_kb_ids

    kb_ids = list_kb_ids()
    return {
        "knowledge_bases": {
            kb_id: {"doc_counts": pg_get_kb_doc_counts(kb_id)} for kb_id in kb_ids
        }
    }
