"""pipeline/queue_worker.py — Background Redis queue consumer (non-Dagster mode).

Runs as an asyncio background task inside FastAPI unless ingestion.queue_worker_enabled is false.
Polls rag:upload:queue and rag:delete:queue, executes pipeline functions in a
ThreadPoolExecutor, and limits concurrency via asyncio.Semaphore.
"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

UPLOAD_QUEUE_KEY = "rag:upload:queue"
DELETE_QUEUE_KEY = "rag:delete:queue"

class QueueWorker:
    def __init__(self, max_workers: int = 4, poll_interval_sec: int = 5) -> None:
        self._poll_interval_sec = poll_interval_sec
        self._max_workers = max_workers
        self._semaphore: asyncio.Semaphore | None = None
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="queue_worker")
        self._running = False

    async def start(self) -> None:
        self._semaphore = asyncio.Semaphore(self._max_workers)
        self._running = True
        logger.info("QueueWorker started: max_workers=%d", self._max_workers)
        while self._running:
            await self._poll()
            await asyncio.sleep(self._poll_interval_sec)

    def stop(self) -> None:
        self._running = False
        self._executor.shutdown(wait=False)

    async def _poll(self) -> None:
        try:
            from infra.redis import get_redis_client
            r = get_redis_client()
        except Exception as e:
            logger.warning("Redis connection failed (queue_worker): %s", e)
            return

        while True:
            raw = r.rpop(UPLOAD_QUEUE_KEY)
            if raw is None:
                break
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid upload event (skipped): %s", raw)
                continue

            kb_id = event.get("kb_id", "")
            object_key = event.get("object_key", "")
            etag = event.get("etag", "")

            from pipeline.ops.meta import try_set_processing

            if not try_set_processing(kb_id, object_key, etag=etag):
                logger.info(
                    "Upload event delayed (processing): kb=%s key=%s", kb_id, object_key
                )
                asyncio.create_task(self._requeue_after_delay(UPLOAD_QUEUE_KEY, raw))
                continue

            logger.info(
                "Dequeued upload event, scheduling ingest: kb=%s key=%s", kb_id, object_key
            )
            asyncio.create_task(self._run_ingest(event))

        while True:
            raw = r.rpop(DELETE_QUEUE_KEY)
            if raw is None:
                break
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid delete event (skipped): %s", raw)
                continue

            kb_id = event.get("kb_id", "")
            object_key = event.get("object_key", "")

            from pipeline.ops.meta import try_set_deleting

            if not try_set_deleting(kb_id, object_key):
                logger.info(
                    "Delete event delayed (busy): kb=%s key=%s", kb_id, object_key
                )
                asyncio.create_task(self._requeue_after_delay(DELETE_QUEUE_KEY, raw))
                continue

            logger.info(
                "Dequeued delete event, scheduling delete: kb=%s key=%s", kb_id, object_key
            )
            asyncio.create_task(self._run_delete(event))

    async def _requeue_after_delay(self, queue_key: str, raw: str) -> None:
        from config.settings import get_settings
        from infra.redis import get_redis_client

        delay = get_settings().ingestion.processing_delay_sec
        await asyncio.sleep(delay)
        get_redis_client().lpush(queue_key, raw)
        logger.debug("Re-queued delayed event to %s", queue_key)

    async def _run_ingest(self, event: dict) -> None:
        assert self._semaphore is not None
        kb_id = event.get("kb_id", "")
        object_key = event.get("object_key", "")
        async with self._semaphore:
            from pipeline.ops.runner import run_ingest_from_key
            loop = asyncio.get_running_loop()
            logger.info("ingest_job started: kb=%s key=%s", kb_id, object_key)
            try:
                chunk_count = await loop.run_in_executor(
                    self._executor,
                    lambda: run_ingest_from_key(
                        kb_id=kb_id,
                        object_key=object_key,
                        etag=event.get("etag", ""),
                        file_size=event.get("file_size", 0),
                        force=event.get("force", False),
                    ),
                )
                logger.info(
                    "ingest_job completed: kb=%s key=%s chunks=%d",
                    kb_id, object_key, chunk_count,
                )
            except Exception as e:
                logger.error("ingest_job failed: kb=%s key=%s err=%s", kb_id, object_key, e)

    async def _run_delete(self, event: dict) -> None:
        assert self._semaphore is not None
        kb_id = event.get("kb_id", "")
        object_key = event.get("object_key", "")
        async with self._semaphore:
            from pipeline.ops.runner import run_delete_pipeline
            loop = asyncio.get_running_loop()
            logger.info("delete_job started: kb=%s key=%s", kb_id, object_key)
            try:
                await loop.run_in_executor(
                    self._executor,
                    lambda: run_delete_pipeline(
                        kb_id=kb_id,
                        object_key=object_key,
                    ),
                )
                logger.info("delete_job completed: kb=%s key=%s", kb_id, object_key)
            except Exception as e:
                logger.error("delete_job failed: kb=%s key=%s err=%s", kb_id, object_key, e)
