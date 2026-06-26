"""pipeline/queue_worker.py — Background Redis queue consumer (non-Dagster mode).

Runs as an asyncio background task inside FastAPI unless queue_worker.enabled is false.
Polls rag:upload:queue and rag:delete:queue, executes pipeline functions in a
ThreadPoolExecutor, and limits concurrency via asyncio.Semaphore.

Duplicate handling: blocked events are written to a Redis sorted set (delay queue)
with score = ready_at timestamp. The same doc_id payload overwrites the existing
entry (ZADD semantics), preventing accumulation. Each poll drains ready entries
back to the main queue before processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from pipeline.enqueue import DELETE_DELAY_KEY, DELETE_QUEUE_KEY, UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY

logger = logging.getLogger(__name__)


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
            try:
                from infra.postgres import get_doc_by_id, update_doc_fields
                doc = get_doc_by_id(doc_id)
                current = doc.get("status", "") if doc else ""
                if current not in ("running", "deleting"):
                    update_doc_fields(doc_id, {"status": "pending"})
            except Exception as e:
                logger.warning("drain_delay: status update failed: doc_id=%s err=%s", doc_id, e)
        r.lpush(main_key, item)
    logger.debug("Drained %d item(s) from %s to %s", len(items), delay_key, main_key)


class QueueWorker:
    def __init__(self, max_workers: int = 4, poll_interval_sec: int = 5, max_per_poll: int = 5) -> None:
        self._poll_interval_sec = poll_interval_sec
        self._max_workers = max_workers
        self._max_per_poll = max_per_poll
        self._semaphore: asyncio.Semaphore | None = None
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="queue_worker")
        self._running = False

    async def start(self) -> None:
        self._semaphore = asyncio.Semaphore(self._max_workers)
        self._running = True
        logger.info("QueueWorker started: max_workers=%d max_per_poll=%d", self._max_workers, self._max_per_poll)
        while self._running:
            more_work = await self._poll()
            if not more_work:
                await asyncio.sleep(self._poll_interval_sec)

    def stop(self) -> None:
        self._running = False
        self._executor.shutdown(wait=False)

    async def _poll(self) -> bool:
        """Return True if either queue hit max_per_poll (more items may remain)."""
        try:
            from infra.redis import get_redis_client
            r = get_redis_client()
        except Exception as e:
            logger.warning("Redis connection failed (queue_worker): %s", e)
            return False

        _drain_delay_queue(r, UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY)
        _drain_delay_queue(r, DELETE_DELAY_KEY, DELETE_QUEUE_KEY)

        from config.settings import get_settings
        delay_sec = get_settings().queue_poll.retry_interval_sec

        upload_count = 0
        while upload_count < self._max_per_poll:
            raw = r.rpop(UPLOAD_QUEUE_KEY)
            if raw is None:
                break
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid upload event (skipped): %s", raw)
                continue

            doc_id = event.get("doc_id", "")
            force = event.get("force", False)
            if not doc_id:
                logger.warning("Upload event missing doc_id (skipped): %s", raw)
                continue

            from infra.postgres import get_doc_by_id
            from pipeline.ops.meta import set_processing

            doc = get_doc_by_id(doc_id)
            if doc:
                s = doc.get("status", "")
                if s in ("running", "deleting"):
                    r.zadd(UPLOAD_DELAY_KEY, {raw: time.time() + delay_sec})
                    logger.info("Upload event delayed (%s): doc_id=%s", s, doc_id)
                    continue

            set_processing(doc_id)
            logger.info("Dequeued upload event, scheduling ingest: doc_id=%s", doc_id)
            asyncio.create_task(self._run_ingest(event))
            upload_count += 1

        delete_count = 0
        while delete_count < self._max_per_poll:
            raw = r.rpop(DELETE_QUEUE_KEY)
            if raw is None:
                break
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid delete event (skipped): %s", raw)
                continue

            doc_id = event.get("doc_id", "")
            if not doc_id:
                logger.warning("Delete event missing doc_id (skipped): %s", raw)
                continue

            from infra.postgres import get_doc_by_id
            from pipeline.ops.meta import set_deleting

            doc = get_doc_by_id(doc_id)
            if doc and doc.get("status") in ("running", "deleting"):
                r.zadd(DELETE_DELAY_KEY, {raw: time.time() + delay_sec})
                logger.info("Delete event delayed (busy): doc_id=%s", doc_id)
                continue

            set_deleting(doc_id)
            logger.info("Dequeued delete event, scheduling delete: doc_id=%s", doc_id)
            asyncio.create_task(self._run_delete(event))
            delete_count += 1

        return upload_count >= self._max_per_poll or delete_count >= self._max_per_poll

    async def _run_ingest(self, event: dict) -> None:
        assert self._semaphore is not None
        doc_id = event.get("doc_id", "")
        force = event.get("force", False)
        async with self._semaphore:
            from pipeline.ops.runner import run_ingest_pipeline
            loop = asyncio.get_running_loop()
            logger.info("ingest_job started: doc_id=%s", doc_id)
            try:
                chunk_count = await loop.run_in_executor(
                    self._executor,
                    lambda: run_ingest_pipeline(doc_id=doc_id, force=force),
                )
                logger.info("ingest_job completed: doc_id=%s chunks=%d", doc_id, chunk_count)
            except Exception as e:
                logger.error("ingest_job failed: doc_id=%s err=%s", doc_id, e)

    async def _run_delete(self, event: dict) -> None:
        assert self._semaphore is not None
        doc_id = event.get("doc_id", "")
        async with self._semaphore:
            from pipeline.ops.runner import run_delete_pipeline
            loop = asyncio.get_running_loop()
            logger.info("delete_job started: doc_id=%s", doc_id)
            try:
                await loop.run_in_executor(
                    self._executor,
                    lambda: run_delete_pipeline(doc_id=doc_id),
                )
                logger.info("delete_job completed: doc_id=%s", doc_id)
            except Exception as e:
                logger.error("delete_job failed: doc_id=%s err=%s", doc_id, e)
