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

from pipeline.enqueue import DELETE_QUEUE_KEY, UPLOAD_QUEUE_KEY

logger = logging.getLogger(__name__)

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

            kb_id = event.get("kb_id", "")
            doc_source = event.get("doc_source", "")
            etag = event.get("etag", "")

            from infra import postgres as postgres_infra
            from pipeline.ops.meta import set_processing

            doc = postgres_infra.get_doc_status(kb_id, doc_source)
            if doc:
                s = doc.get("status", "")
                if s == "deleting":
                    asyncio.create_task(self._requeue_after_delay(UPLOAD_QUEUE_KEY, raw))
                    logger.info("Upload event delayed (deleting): kb=%s key=%s", kb_id, doc_source)
                    continue
                elif s == "running":
                    asyncio.create_task(self._requeue_after_delay(UPLOAD_QUEUE_KEY, raw))
                    logger.info("Upload event delayed (running): kb=%s key=%s", kb_id, doc_source)
                    continue

            set_processing(kb_id, doc_source)
            logger.info(
                "Dequeued upload event, scheduling ingest: kb=%s key=%s", kb_id, doc_source
            )
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

            kb_id = event.get("kb_id", "")
            doc_source = event.get("doc_source", "")

            from infra import postgres as postgres_infra
            from pipeline.ops.meta import set_deleting

            doc = postgres_infra.get_doc_status(kb_id, doc_source)
            if doc and doc.get("status") in ("running", "deleting"):
                asyncio.create_task(self._requeue_after_delay(DELETE_QUEUE_KEY, raw))
                logger.info("Delete event delayed (busy): kb=%s key=%s", kb_id, doc_source)
                continue

            set_deleting(kb_id, doc_source)

            logger.info(
                "Dequeued delete event, scheduling delete: kb=%s key=%s", kb_id, doc_source
            )
            asyncio.create_task(self._run_delete(event))
            delete_count += 1

        return upload_count >= self._max_per_poll or delete_count >= self._max_per_poll

    async def _requeue_after_delay(self, queue_key: str, raw: str) -> None:
        from config.settings import get_settings
        from infra.redis import get_redis_client

        delay = get_settings().queue_poll.retry_interval_sec
        await asyncio.sleep(delay)

        try:
            event = json.loads(raw)
            kb_id = event.get("kb_id", "")
            doc_source = event.get("doc_source", "")
            if kb_id and doc_source:
                from infra import postgres as pg
                from pipeline.ops.meta import set_pending
                doc = pg.get_doc_status(kb_id, doc_source)
                current = doc.get("status", "") if doc else ""
                if current not in ("running", "deleting"):
                    set_pending(kb_id, doc_source)
        except Exception as e:
            logger.warning("_requeue_after_delay status check failed: %s", e)

        get_redis_client().lpush(queue_key, raw)
        logger.debug("Re-queued delayed event to %s", queue_key)

    async def _run_ingest(self, event: dict) -> None:
        assert self._semaphore is not None
        kb_id = event.get("kb_id", "")
        doc_source = event.get("doc_source", "")
        async with self._semaphore:
            from pipeline.ops.runner import run_ingest_pipeline
            loop = asyncio.get_running_loop()
            logger.info("ingest_job started: kb=%s key=%s", kb_id, doc_source)
            try:
                chunk_count = await loop.run_in_executor(
                    self._executor,
                    lambda: run_ingest_pipeline(
                        kb_id=kb_id,
                        doc_source=doc_source,
                        etag=event.get("etag", ""),
                        file_size=event.get("file_size", 0),
                        force=event.get("force", False),
                    ),
                )
                logger.info(
                    "ingest_job completed: kb=%s key=%s chunks=%d",
                    kb_id, doc_source, chunk_count,
                )
            except Exception as e:
                logger.error("ingest_job failed: kb=%s key=%s err=%s", kb_id, doc_source, e)

    async def _run_delete(self, event: dict) -> None:
        assert self._semaphore is not None
        kb_id = event.get("kb_id", "")
        doc_source = event.get("doc_source", "")
        async with self._semaphore:
            from pipeline.ops.runner import run_delete_pipeline
            loop = asyncio.get_running_loop()
            logger.info("delete_job started: kb=%s key=%s", kb_id, doc_source)
            try:
                await loop.run_in_executor(
                    self._executor,
                    lambda: run_delete_pipeline(
                        kb_id=kb_id,
                        doc_source=doc_source,
                    ),
                )
                logger.info("delete_job completed: kb=%s key=%s", kb_id, doc_source)
            except Exception as e:
                logger.error("delete_job failed: kb=%s key=%s err=%s", kb_id, doc_source, e)
