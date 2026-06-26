"""pipeline/enqueue.py — Redis queue push helpers for upload and delete events."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

UPLOAD_QUEUE_KEY = "rag:upload:queue"
DELETE_QUEUE_KEY = "rag:delete:queue"
UPLOAD_DELAY_KEY = "rag:upload:delay"
DELETE_DELAY_KEY = "rag:delete:delay"


def enqueue_upload_event(doc_id: str, force: bool = False) -> None:
    """Push an ingest event to the Redis upload queue.

    Sets status=pending unless the doc is already running or deleting.
    """
    from infra.postgres import get_doc_by_id, update_doc_fields
    from infra.redis import get_redis_client

    doc = get_doc_by_id(doc_id)
    if doc is None:
        logger.warning("enqueue_upload_event: doc not found: doc_id=%s", doc_id)
        return

    current = doc.get("status", "")
    if current not in ("running", "deleting"):
        update_doc_fields(doc_id, {"status": "pending"})

    payload = json.dumps({"doc_id": doc_id, "force": force})
    get_redis_client().lpush(UPLOAD_QUEUE_KEY, payload)
    logger.info("Upload event enqueued: doc_id=%s", doc_id)


def enqueue_delete_event(doc_id: str) -> None:
    """Push a delete event to the Redis delete queue.

    Sets status=pending unless the doc is already running or deleting.
    """
    from infra.postgres import get_doc_by_id, update_doc_fields
    from infra.redis import get_redis_client

    doc = get_doc_by_id(doc_id)
    if doc is None:
        logger.warning("enqueue_delete_event: doc not found: doc_id=%s", doc_id)
        return

    current = doc.get("status", "")
    if current not in ("running", "deleting"):
        update_doc_fields(doc_id, {"status": "pending"})

    payload = json.dumps({"doc_id": doc_id})
    get_redis_client().lpush(DELETE_QUEUE_KEY, payload)
    logger.info("Delete event enqueued: doc_id=%s", doc_id)
