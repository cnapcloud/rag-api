"""QueueWorker unit tests — concurrency guard (_poll logic)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


def _make_redis(upload_events=None, delete_events=None, processing_keys=None):
    store: dict = {}
    lists: dict = {}
    hashes: dict = {}
    sets: dict = {}

    for e in (upload_events or []):
        key = "rag:upload:queue"
        lists.setdefault(key, []).append(json.dumps(e))
    for e in (delete_events or []):
        key = "rag:delete:queue"
        lists.setdefault(key, []).append(json.dumps(e))
    for kb_id, object_key in (processing_keys or []):
        hashes[f"doc:{kb_id}:{object_key}"] = {"status": "running"}

    class FakeRedis:
        def rpop(self, key):
            lst = lists.get(key, [])
            return lst.pop() if lst else None

        def lpush(self, key, value):
            lists.setdefault(key, []).insert(0, value)

        def hset(self, key, mapping=None, **kw):
            hashes.setdefault(key, {}).update({k: str(v) for k, v in (mapping or {}).items()})

        def hgetall(self, key):
            return dict(hashes.get(key, {}))

        def sadd(self, key, *values):
            sets.setdefault(key, set()).update(values)

        def get(self, key):
            return store.get(key)

        def set(self, key, value):
            store[key] = value

    return FakeRedis(), lists


def _run_poll(worker, fake_redis):
    with patch("infra.redis.get_redis_client", return_value=fake_redis):
        asyncio.run(worker._poll())


async def _run_poll_async(worker, fake_redis):
    with patch("infra.redis.get_redis_client", return_value=fake_redis):
        await worker._poll()


def test_poll_upload_not_processing_dispatches():
    """Upload event, doc not processing → _run_ingest task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, lists = _make_redis(
        upload_events=[{"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}]
    )
    dispatched = []

    original_create_task = asyncio.create_task

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with patch("infra.redis.get_redis_client", return_value=fake_redis):
        with patch("asyncio.create_task", side_effect=fake_create_task):
            asyncio.run(worker._poll())

    assert any("_run_ingest" in d for d in dispatched)
    assert not any("_requeue_after_delay" in d for d in dispatched)


def test_poll_upload_while_processing_requeues():
    """Upload event, doc is processing → _requeue_after_delay task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, lists = _make_redis(
        upload_events=[{"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}],
        processing_keys=[("kb-test", "doc.pdf")],
    )
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with patch("infra.redis.get_redis_client", return_value=fake_redis):
        with patch("asyncio.create_task", side_effect=fake_create_task):
            asyncio.run(worker._poll())

    assert any("_requeue_after_delay" in d for d in dispatched)
    assert not any("_run_ingest" in d for d in dispatched)


def test_poll_delete_not_processing_dispatches():
    """Delete event, doc not processing → _run_delete task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, lists = _make_redis(
        delete_events=[{"kb_id": "kb-test", "object_key": "doc.pdf"}]
    )
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with patch("infra.redis.get_redis_client", return_value=fake_redis):
        with patch("asyncio.create_task", side_effect=fake_create_task):
            asyncio.run(worker._poll())

    assert any("_run_delete" in d for d in dispatched)
    assert not any("_requeue_after_delay" in d for d in dispatched)


def test_poll_delete_while_processing_requeues():
    """Delete event, doc is processing → _requeue_after_delay task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, lists = _make_redis(
        delete_events=[{"kb_id": "kb-test", "object_key": "doc.pdf"}],
        processing_keys=[("kb-test", "doc.pdf")],
    )
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with patch("infra.redis.get_redis_client", return_value=fake_redis):
        with patch("asyncio.create_task", side_effect=fake_create_task):
            asyncio.run(worker._poll())

    assert any("_requeue_after_delay" in d for d in dispatched)
    assert not any("_run_delete" in d for d in dispatched)


def test_poll_upload_while_deleting_requeues():
    """Upload event, doc is deleting → _requeue_after_delay task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, lists = _make_redis(
        upload_events=[{"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}],
    )
    fake_redis.hset("doc:kb-test:doc.pdf", {"status": "deleting"})
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with patch("infra.redis.get_redis_client", return_value=fake_redis):
        with patch("asyncio.create_task", side_effect=fake_create_task):
            asyncio.run(worker._poll())

    assert any("_requeue_after_delay" in d for d in dispatched)
    assert not any("_run_ingest" in d for d in dispatched)


def test_poll_delete_while_deleting_requeues():
    """Delete event, doc is already deleting → _requeue_after_delay task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, lists = _make_redis(
        delete_events=[{"kb_id": "kb-test", "object_key": "doc.pdf"}],
    )
    fake_redis.hset("doc:kb-test:doc.pdf", {"status": "deleting"})
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with patch("infra.redis.get_redis_client", return_value=fake_redis):
        with patch("asyncio.create_task", side_effect=fake_create_task):
            asyncio.run(worker._poll())

    assert any("_requeue_after_delay" in d for d in dispatched)
    assert not any("_run_delete" in d for d in dispatched)


def test_requeue_after_delay_pushes_back():
    """_requeue_after_delay sleeps then lpushes the raw event back to the queue."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    raw = json.dumps({"kb_id": "kb-test", "object_key": "doc.pdf"})
    pushed = []

    fake_redis = MagicMock()
    fake_redis.lpush.side_effect = lambda key, val: pushed.append((key, val))

    async def run():
        with patch("config.settings.get_settings") as mock_settings:
            mock_settings.return_value.ingestion.processing_delay_sec = 0
            with patch("infra.redis.get_redis_client", return_value=fake_redis):
                await worker._requeue_after_delay("rag:upload:queue", raw)

    asyncio.run(run())

    assert len(pushed) == 1
    assert pushed[0] == ("rag:upload:queue", raw)
