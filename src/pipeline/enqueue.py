"""pipeline/enqueue.py — Redis queue push helpers for upload and delete events.

Used by the webhook handler, API routes, CLI, Dagster sensor, and QueueWorker.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

UPLOAD_QUEUE_KEY = "rag:upload:queue"
DELETE_QUEUE_KEY = "rag:delete:queue"


def enqueue_upload_event(
    kb_id: str,
    doc_source: str,
    etag: str,
    file_size: int = 0,
    force: bool = False,
) -> None:
    """Push a PUT event to the Redis upload queue.

    Sets status=pending before pushing unless the doc is already running or deleting
    (Option A: no status change when a concurrent run is active).
    """
    from infra import postgres as pg
    from infra.redis import get_redis_client
    from pipeline.ops.meta import set_pending

    payload = json.dumps(
        {"kb_id": kb_id, "doc_source": doc_source, "etag": etag, "file_size": file_size, "force": force}
    )
    doc = pg.get_doc_status(kb_id, doc_source)
    current = doc.get("status", "") if doc else ""
    if current not in ("running", "deleting"):
        set_pending(kb_id, doc_source)
    get_redis_client().lpush(UPLOAD_QUEUE_KEY, payload)
    logger.info("Upload event enqueued: kb=%s key=%s", kb_id, doc_source)


def enqueue_delete_event(kb_id: str, doc_source: str) -> None:
    """Push a DELETE event to the Redis delete queue.

    Sets status=pending before pushing unless the doc is already running or deleting.
    """
    from infra import postgres as pg
    from infra.redis import get_redis_client
    from pipeline.ops.meta import set_pending

    payload = json.dumps({"kb_id": kb_id, "doc_source": doc_source})
    doc = pg.get_doc_status(kb_id, doc_source)
    current = doc.get("status", "") if doc else ""
    if current not in ("running", "deleting"):
        set_pending(kb_id, doc_source)
    get_redis_client().lpush(DELETE_QUEUE_KEY, payload)
    logger.info("Delete event enqueued: kb=%s key=%s", kb_id, doc_source)
