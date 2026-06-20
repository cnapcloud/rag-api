"""QueueWorker unit tests — concurrency guard (_poll logic)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch


def _make_redis(upload_events=None, delete_events=None):
    """Build a minimal FakeRedis for queue operations only."""
    lists: dict = {}

    for e in (upload_events or []):
        lists.setdefault("rag:upload:queue", []).append(json.dumps(e))
    for e in (delete_events or []):
        lists.setdefault("rag:delete:queue", []).append(json.dumps(e))

    class FakeRedis:
        def rpop(self, key):
            lst = lists.get(key, [])
            return lst.pop() if lst else None

        def lpush(self, key, value):
            lists.setdefault(key, []).insert(0, value)

    return FakeRedis(), lists


def _run_poll(worker, fake_redis, pg_doc=None):
    """Run worker._poll with mocked Redis queue and optional Postgres doc status."""
    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value=pg_doc),
    ):
        asyncio.run(worker._poll())


def test_poll_upload_not_processing_dispatches():
    """Upload event, doc not processing -> _run_ingest task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _ = _make_redis(
        upload_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}]
    )
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value=None),
        patch("infra.postgres.set_doc_status"),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        asyncio.run(worker._poll())

    assert any("_run_ingest" in d for d in dispatched)
    assert not any("_requeue_after_delay" in d for d in dispatched)


def test_poll_upload_while_processing_requeues():
    """Upload event, doc is processing -> _requeue_after_delay task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _ = _make_redis(
        upload_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}]
    )
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value={"status": "running", "run_id": "r1"}),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        asyncio.run(worker._poll())

    assert any("_requeue_after_delay" in d for d in dispatched)
    assert not any("_run_ingest" in d for d in dispatched)


def test_poll_delete_not_processing_dispatches():
    """Delete event, doc not processing -> _run_delete task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _ = _make_redis(delete_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf"}])
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value=None),
        patch("infra.postgres.set_doc_status"),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        asyncio.run(worker._poll())

    assert any("_run_delete" in d for d in dispatched)
    assert not any("_requeue_after_delay" in d for d in dispatched)


def test_poll_delete_while_processing_requeues():
    """Delete event, doc is processing -> _requeue_after_delay task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _ = _make_redis(delete_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf"}])
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value={"status": "running", "run_id": "r1"}),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        asyncio.run(worker._poll())

    assert any("_requeue_after_delay" in d for d in dispatched)
    assert not any("_run_delete" in d for d in dispatched)


def test_poll_upload_while_processing_no_run_id_requeues():
    """Upload event, doc is running with no run_id (QueueWorker mode) -> must requeue.

    Previously fell through due to 'run_id=""' check — now fixed.
    """
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _ = _make_redis(
        upload_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}]
    )
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value={"status": "running", "run_id": ""}),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        asyncio.run(worker._poll())

    assert any("_requeue_after_delay" in d for d in dispatched)
    assert not any("_run_ingest" in d for d in dispatched)


def test_poll_upload_while_deleting_requeues():
    """Upload event, doc is deleting -> _requeue_after_delay task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _ = _make_redis(
        upload_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}]
    )
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value={"status": "deleting", "run_id": ""}),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        asyncio.run(worker._poll())

    assert any("_requeue_after_delay" in d for d in dispatched)
    assert not any("_run_ingest" in d for d in dispatched)


def test_poll_delete_while_deleting_requeues():
    """Delete event, doc is already deleting -> _requeue_after_delay task created."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _ = _make_redis(delete_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf"}])
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value={"status": "deleting", "run_id": ""}),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        asyncio.run(worker._poll())

    assert any("_requeue_after_delay" in d for d in dispatched)
    assert not any("_run_delete" in d for d in dispatched)


def test_poll_upload_fills_limit_delete_still_runs():
    """Upload queue at max_per_poll capacity -> delete queue is still processed independently."""
    from pipeline.queue_worker import QueueWorker

    max_per_poll = 5
    worker = QueueWorker(max_per_poll=max_per_poll)
    worker._semaphore = asyncio.Semaphore(10)

    upload_events = [
        {"kb_id": "kb-test", "doc_source": f"doc{i}.pdf", "etag": f"e{i}", "file_size": 0, "force": False}
        for i in range(max_per_poll)
    ]
    delete_events = [{"kb_id": "kb-test", "doc_source": f"old{i}.pdf"} for i in range(3)]
    fake_redis, _ = _make_redis(upload_events=upload_events, delete_events=delete_events)

    ingest_dispatched = []
    delete_dispatched = []

    def fake_create_task(coro, **kw):
        name = coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro)
        if "_run_ingest" in name:
            ingest_dispatched.append(name)
        elif "_run_delete" in name:
            delete_dispatched.append(name)
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value=None),
        patch("infra.postgres.set_doc_status"),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        asyncio.run(worker._poll())

    assert len(ingest_dispatched) == max_per_poll
    assert len(delete_dispatched) == 3


def test_poll_returns_true_when_upload_hits_limit():
    """_poll returns True when upload queue reaches max_per_poll (more items may remain)."""
    from pipeline.queue_worker import QueueWorker

    max_per_poll = 5
    worker = QueueWorker(max_per_poll=max_per_poll)
    worker._semaphore = asyncio.Semaphore(10)

    upload_events = [
        {"kb_id": "kb-test", "doc_source": f"doc{i}.pdf", "etag": f"e{i}", "file_size": 0, "force": False}
        for i in range(max_per_poll)
    ]
    fake_redis, _ = _make_redis(upload_events=upload_events)

    def fake_create_task(coro, **kw):
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value=None),
        patch("infra.postgres.set_doc_status"),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        result = asyncio.run(worker._poll())

    assert result is True


def test_poll_returns_false_when_queues_drained():
    """_poll returns False when both queues exhaust before hitting max_per_poll."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker(max_per_poll=5)
    worker._semaphore = asyncio.Semaphore(10)

    upload_events = [
        {"kb_id": "kb-test", "doc_source": f"doc{i}.pdf", "etag": f"e{i}", "file_size": 0, "force": False}
        for i in range(3)
    ]
    delete_events = [{"kb_id": "kb-test", "doc_source": f"old{i}.pdf"} for i in range(2)]
    fake_redis, _ = _make_redis(upload_events=upload_events, delete_events=delete_events)

    def fake_create_task(coro, **kw):
        coro.close()
        return MagicMock()

    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("infra.postgres.get_doc_status", return_value=None),
        patch("infra.postgres.set_doc_status"),
        patch("asyncio.create_task", side_effect=fake_create_task),
    ):
        result = asyncio.run(worker._poll())

    assert result is False


def test_requeue_after_delay_sets_pending_when_doc_not_running():
    """_requeue_after_delay sets pending then lpushes when doc is not running/deleting."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    raw = json.dumps({"kb_id": "kb-test", "doc_source": "doc.pdf"})
    pushed = []
    pending_calls = []

    fake_redis = MagicMock()
    fake_redis.lpush.side_effect = lambda key, val: pushed.append((key, val))

    async def run():
        with (
            patch("config.settings.get_settings") as mock_settings,
            patch("infra.redis.get_redis_client", return_value=fake_redis),
            patch("infra.postgres.get_doc_status", return_value={"status": "indexed"}),
            patch("pipeline.ops.meta.set_pending", side_effect=lambda kb, src: pending_calls.append((kb, src))),
        ):
            mock_settings.return_value.queue_poll.retry_interval_sec = 0
            await worker._requeue_after_delay("rag:upload:queue", raw)

    asyncio.run(run())

    assert len(pushed) == 1
    assert pushed[0] == ("rag:upload:queue", raw)
    assert len(pending_calls) == 1
    assert pending_calls[0] == ("kb-test", "doc.pdf")


def test_requeue_after_delay_skips_pending_when_still_running():
    """_requeue_after_delay skips set_pending and just lpushes when doc is still running."""
    from pipeline.queue_worker import QueueWorker

    worker = QueueWorker()
    raw = json.dumps({"kb_id": "kb-test", "doc_source": "doc.pdf"})
    pushed = []
    pending_calls = []

    fake_redis = MagicMock()
    fake_redis.lpush.side_effect = lambda key, val: pushed.append((key, val))

    async def run():
        with (
            patch("config.settings.get_settings") as mock_settings,
            patch("infra.redis.get_redis_client", return_value=fake_redis),
            patch("infra.postgres.get_doc_status", return_value={"status": "running", "run_id": "r1"}),
            patch("pipeline.ops.meta.set_pending", side_effect=lambda kb, src: pending_calls.append((kb, src))),
        ):
            mock_settings.return_value.queue_poll.retry_interval_sec = 0
            await worker._requeue_after_delay("rag:upload:queue", raw)

    asyncio.run(run())

    assert len(pushed) == 1
    assert len(pending_calls) == 0
