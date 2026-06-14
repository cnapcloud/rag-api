"""event_queue_sensor — Redis 큐(PUT/DELETE)에 쌓인 이벤트를 소비해 job을 트리거한다."""

from __future__ import annotations

import json
import logging
import time
from uuid import uuid4

from dagster import DefaultSensorStatus, RunRequest, SensorEvaluationContext, SkipReason, sensor

from dagster_pipeline.jobs.delete_job import delete_job
from dagster_pipeline.jobs.ingest_job import ingest_job

logger = logging.getLogger(__name__)

UPLOAD_QUEUE_KEY = "rag:upload:queue"
DELETE_QUEUE_KEY = "rag:delete:queue"
UPLOAD_DELAY_KEY = "rag:upload:delay"
DELETE_DELAY_KEY = "rag:delete:delay"


from config.settings import get_settings as _get_settings

_poll_interval_sec = _get_settings().ingestion.poll_interval_sec
_max_runs_per_tick = _get_settings().ingestion.max_runs_per_tick


def _drain_delay_queue(r, delay_key: str, main_key: str) -> None:
    """Move ready items from the delay sorted set back to the main queue."""
    now = time.time()
    items = r.zrangebyscore(delay_key, 0, now)
    if not items:
        return
    r.zrem(delay_key, *items)
    for item in items:
        r.lpush(main_key, item)
    logger.debug("Drained %d item(s) from %s to %s", len(items), delay_key, main_key)


@sensor(
    jobs=[ingest_job, delete_job],
    minimum_interval_seconds=_poll_interval_sec,
    default_status=DefaultSensorStatus.RUNNING,
    description="Redis 큐(PUT/DELETE)에서 이벤트를 소비해 ingest_job / delete_job을 트리거한다.",
)
def event_queue_sensor(context: SensorEvaluationContext):
    if _get_settings().ingestion.queue_worker_enabled:
        yield SkipReason("QueueWorker is enabled — Dagster sensor is inactive")
        return

    try:
        from infra.redis import get_redis_client

        r = get_redis_client()
    except Exception as e:
        logger.warning("Redis connection failed (event_queue_sensor): %s", e)
        return

    delay_sec = _get_settings().ingestion.processing_delay_sec

    # Drain delay queues first — move ready items back to main queues
    _drain_delay_queue(r, UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY)
    _drain_delay_queue(r, DELETE_DELAY_KEY, DELETE_QUEUE_KEY)

    # PUT queue → ingest_job
    count = 0
    while count < _max_runs_per_tick:
        raw = r.rpop(UPLOAD_QUEUE_KEY)
        if raw is None:
            break

        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid PUT event format: %s", raw)
            continue

        kb_id = event.get("kb_id", "")
        object_key = event.get("object_key", "")
        etag = event.get("etag", "")
        file_size = event.get("file_size", 0)
        force = event.get("force", False)

        from infra import redis as redis_infra
        from pipeline.ops.meta import set_failed, set_processing

        prev = redis_infra.get_doc_status(kb_id, object_key)
        if prev:
            s = prev.get("status", "")
            if s == "deleting":
                r.zadd(UPLOAD_DELAY_KEY, {raw: time.time() + delay_sec})
                logger.info("Upload event delayed (deleting): kb=%s key=%s delay=%ss", kb_id, object_key, delay_sec)
                continue
            elif s == "running":
                prev_run_id = prev.get("run_id", "")
                if prev_run_id:
                    run = context.instance.get_run_by_id(prev_run_id)
                    if run is not None and not run.is_finished:
                        r.zadd(UPLOAD_DELAY_KEY, {raw: time.time() + delay_sec})
                        logger.info("Upload event delayed (running): kb=%s key=%s delay=%ss", kb_id, object_key, delay_sec)
                        continue
                    set_failed(
                        kb_id, object_key,
                        f"Recovered: previous run no longer active (run_id={prev_run_id})",
                        run_id=prev_run_id,
                    )
                    logger.warning("Zombie run recovered: kb=%s key=%s prev_run_id=%s", kb_id, object_key, prev_run_id)
                # run_id="" → dispatch lock remnant (job not yet started), fall through to dispatch

        set_processing(kb_id, object_key, etag=etag)
        logger.info("Dispatching ingest_job from queue: kb=%s key=%s", kb_id, object_key)
        yield RunRequest(
            run_key=str(uuid4()),
            job_name=ingest_job.name,
            run_config={
                "ops": {
                    "validate_op": {
                        "config": {
                            "kb_id": kb_id,
                            "object_key": object_key,
                            "etag": etag,
                            "file_size": file_size,
                            "force": force,
                        }
                    }
                }
            },
            tags={"kb_id": kb_id, "trigger": "api_upload"},
        )
        count += 1

    # DELETE queue → delete_job
    while count < _max_runs_per_tick:
        raw = r.rpop(DELETE_QUEUE_KEY)
        if raw is None:
            break

        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid DELETE event format: %s", raw)
            continue

        kb_id = event.get("kb_id", "")
        object_key = event.get("object_key", "")

        from pipeline.ops.meta import try_set_deleting

        if not try_set_deleting(kb_id, object_key):
            ready_at = time.time() + delay_sec
            r.zadd(DELETE_DELAY_KEY, {raw: ready_at})
            logger.info(
                "Delete event delayed (busy): kb=%s key=%s delay=%ss",
                kb_id, object_key, delay_sec,
            )
            continue

        logger.info("Dispatching delete_job from queue: kb=%s key=%s", kb_id, object_key)
        yield RunRequest(
            run_key=str(uuid4()),
            job_name=delete_job.name,
            run_config={
                "ops": {
                    "delete_chunks_op": {
                        "config": {
                            "kb_id": kb_id,
                            "object_key": object_key,
                        }
                    }
                }
            },
            tags={"kb_id": kb_id, "trigger": "api_delete"},
        )
        count += 1

    if count:
        logger.info("event_queue_sensor: %d RunRequest(s) created", count)
    else:
        yield SkipReason("No events in Redis queue — no jobs to trigger")


def enqueue_upload_event(
    kb_id: str,
    object_key: str,
    etag: str,
    file_size: int = 0,
    force: bool = False,
) -> None:
    """Push a PUT event to the Redis upload queue."""
    from infra.redis import get_redis_client

    r = get_redis_client()
    payload = json.dumps(
        {"kb_id": kb_id, "object_key": object_key, "etag": etag, "file_size": file_size, "force": force}
    )
    r.lpush(UPLOAD_QUEUE_KEY, payload)


def enqueue_delete_event(kb_id: str, object_key: str) -> None:
    """Push a DELETE event to the Redis delete queue."""
    from infra.redis import get_redis_client

    r = get_redis_client()
    payload = json.dumps({"kb_id": kb_id, "object_key": object_key})
    r.lpush(DELETE_QUEUE_KEY, payload)
