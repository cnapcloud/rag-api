"""Internal router — S3-compatible storage webhook event receiver."""

from __future__ import annotations

import logging

from urllib.parse import unquote_plus

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


# ──────────────────────────────────────────────
# S3 webhook payload models
# ──────────────────────────────────────────────

class _S3Object(BaseModel):
    key: str
    size: int = 0
    eTag: str = ""


class _S3Info(BaseModel):
    object: _S3Object


class _S3Record(BaseModel):
    eventName: str
    s3: _S3Info


class S3WebhookPayload(BaseModel):
    EventName: str = ""
    Records: list[_S3Record] = []


# ──────────────────────────────────────────────
# Endpoint
# ──────────────────────────────────────────────

@router.post("/s3-event", status_code=202)
async def handle_storage_event(payload: S3WebhookPayload):
    """
    Receive S3-compatible object storage notifications (s3:ObjectCreated:Put / s3:ObjectRemoved:Delete).
    Always pushes to Redis queue. Consumer is either event_queue_sensor (Dagster) or QueueWorker (background).
    Returns 202 immediately.
    """
    from dagster_pipeline.sensors.event_queue_sensor import enqueue_delete_event, enqueue_upload_event

    logger.info("Storage webhook received: records=%d", len(payload.Records))

    for record in payload.Records:
        event_name = record.eventName
        obj_path = unquote_plus(record.s3.object.key)
        parts = obj_path.split("/", 1)
        if len(parts) < 2:
            logger.warning("Unexpected object path (no KB prefix): %s", obj_path)
            continue

        kb_id, doc_source = parts[0], parts[1]
        if not doc_source:
            logger.warning("Empty doc_source in event: %s", obj_path)
            continue

        etag = record.s3.object.eTag.strip('"')
        size = record.s3.object.size

        if event_name.startswith("s3:ObjectCreated"):
            logger.info("Storage webhook PUT: kb=%s key=%s etag=%s", kb_id, doc_source, etag)
            enqueue_upload_event(kb_id=kb_id, doc_source=doc_source, etag=etag, file_size=size)

        elif event_name.startswith("s3:ObjectRemoved"):
            logger.info("Storage webhook DELETE: kb=%s key=%s", kb_id, doc_source)
            enqueue_delete_event(kb_id=kb_id, doc_source=doc_source)

        else:
            logger.debug("Unhandled storage event: %s", event_name)

    return {"accepted": len(payload.Records)}
