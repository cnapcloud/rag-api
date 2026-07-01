"""event_queue_sensor — consume Redis queue events and trigger Dagster jobs."""

from __future__ import annotations

import json
import logging
import time
from uuid import uuid4

from dagster import DefaultSensorStatus, RunRequest, SensorEvaluationContext, SkipReason, sensor

from rag_api.defs.jobs.delete_job import delete_job
from rag_api.defs.jobs.ingest_job import ingest_job

from rag_api.pipeline.queue.enqueue import DELETE_DELAY_KEY, DELETE_QUEUE_KEY, UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY

logger = logging.getLogger(__name__)


from rag_api.config.settings import get_settings as _get_settings

_poll_interval_sec = _get_settings().queue_poll.poll_interval_sec
_max_per_poll = _get_settings().queue_poll.max_per_poll


def _drain_delay_queue(r, delay_key: str, main_key: str) -> None:
    """Move ready items from the delay sorted set back to the main queue."""
    now = time.time()
    items = r.zrangebyscore(delay_key, 0, now)
    if not items:
        return
    r.zrem(delay_key, *items)
    for item in items:
        try:
            event = json.loads(item)
        except json.JSONDecodeError:
            event = {}
        doc_id = event.get("doc_id", "")
        if doc_id:
            from rag_api.infra.postgres import get_doc_by_id
            from rag_api.pipeline.utils.doc_state import set_pending
            doc = get_doc_by_id(doc_id)
            current = doc.get("status", "") if doc else ""
            if current not in ("running", "deleting"):
                set_pending(doc_id)
        r.lpush(main_key, item)
    logger.debug("Drained %d item(s) from %s to %s", len(items), delay_key, main_key)


def _is_blocked_by_active_run(
    context: SensorEvaluationContext,
    r,
    doc: dict,
    delay_key: str,
    delay_sec: float,
    raw: str,
    doc_id: str,
) -> bool:
    """Return True and enqueue delay if an active Dagster run is blocking this event."""
    from rag_api.pipeline.ops.meta import set_failed

    s = doc.get("status", "")
    if s != "running":
        return False

    prev_run_id = doc.get("run_id", "")
    if prev_run_id:
        run = context.instance.get_run_by_id(prev_run_id)
        if run is not None and not run.is_finished:
            r.zadd(delay_key, {raw: time.time() + delay_sec})
            logger.info("Event delayed (%s): doc_id=%s delay=%ss", s, doc_id, delay_sec)
            return True
        set_failed(
            doc_id,
            f"Recovered: previous run no longer active (run_id={prev_run_id})",
            run_id=prev_run_id,
        )
        logger.warning("Zombie run recovered: doc_id=%s prev_run_id=%s", doc_id, prev_run_id)

    return False


@sensor(
    jobs=[ingest_job, delete_job],
    minimum_interval_seconds=_poll_interval_sec,
    default_status=DefaultSensorStatus.RUNNING,
    description="Consume Redis queue events (PUT/DELETE) and trigger ingest_job / delete_job.",
)
def event_queue_sensor(context: SensorEvaluationContext):
    if _get_settings().queue_worker.enabled:
        yield SkipReason("QueueWorker is enabled — Dagster sensor is inactive")
        return

    try:
        from rag_api.infra.redis import get_redis_client
        r = get_redis_client()
    except Exception as e:
        logger.warning("Redis connection failed (event_queue_sensor): %s", e)
        return

    delay_sec = _get_settings().queue_poll.retry_interval_sec

    _drain_delay_queue(r, UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY)
    _drain_delay_queue(r, DELETE_DELAY_KEY, DELETE_QUEUE_KEY)

    count = 0

    # PUT queue -> ingest_job
    while count < _max_per_poll:
        raw = r.rpop(UPLOAD_QUEUE_KEY)
        if not isinstance(raw, (bytes, str)):
            if raw is not None:
                logger.warning("Unexpected type from upload queue: %s", type(raw).__name__)
            break
         
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid PUT event format: %s", raw)
            continue

        doc_id = event.get("doc_id", "")
        force = event.get("force", False)
        if not doc_id:
            logger.warning("PUT event missing doc_id (skipped): %s", raw)
            continue

        from rag_api.infra.postgres import get_doc_by_id
        from rag_api.pipeline.ops.meta import set_processing

        doc = get_doc_by_id(doc_id)
        if doc and doc.get("status") == "deleting":
            r.zadd(UPLOAD_DELAY_KEY, {raw: time.time() + delay_sec})
            logger.info("Upload event delayed (deleting): doc_id=%s", doc_id)
            continue
        if doc and _is_blocked_by_active_run(context, r, doc, UPLOAD_DELAY_KEY, delay_sec, raw, doc_id):
            continue

        set_processing(doc_id)
        kb_id = doc["kb_id"] if doc else ""
        logger.info("Dispatching ingest_job from queue: doc_id=%s kb=%s", doc_id, kb_id)
        yield RunRequest(
            run_key=str(uuid4()),
            job_name=ingest_job.name,
            run_config={
                "ops": {
                    "validate_op": {
                        "config": {
                            "doc_id": doc_id,
                            "force": force,
                        }
                    }
                }
            },
            tags={"doc_id": doc_id, "kb_id": kb_id, "trigger": "api_upload"},
        )
        count += 1

    # DELETE queue -> delete_job
    while count < _max_per_poll:
        raw = r.rpop(DELETE_QUEUE_KEY)
        if raw is None:
            break

        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid DELETE event format: %s", raw)
            continue

        doc_id = event.get("doc_id", "")
        force = event.get("force", False)
        if not doc_id:
            logger.warning("DELETE event missing doc_id (skipped): %s", raw)
            continue

        from rag_api.infra.postgres import get_doc_by_id

        doc = get_doc_by_id(doc_id)
        if doc and _is_blocked_by_active_run(context, r, doc, DELETE_DELAY_KEY, delay_sec, raw, doc_id):
            continue

        kb_id = doc["kb_id"] if doc else ""
        logger.info("Dispatching delete_job from queue: doc_id=%s kb=%s force=%s", doc_id, kb_id, force)
        yield RunRequest(
            run_key=str(uuid4()),
            job_name=delete_job.name,
            run_config={
                "ops": {
                    "delete_op": {
                        "config": {
                            "doc_id": doc_id,
                            "force": force,
                        }
                    }
                }
            },
            tags={"doc_id": doc_id, "kb_id": kb_id, "trigger": "api_delete"},
        )
        count += 1

    if count:
        logger.info("event_queue_sensor: %d RunRequest(s) created", count)
    else:
        yield SkipReason("No events in Redis queue — no jobs to trigger")
