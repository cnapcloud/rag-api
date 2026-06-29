"""QueueWorker unit tests — concurrency guard (_poll logic)."""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

DOC_ID = "11111111-1111-1111-1111-111111111111"
DOC_ID_2 = "22222222-2222-2222-2222-222222222222"

UPLOAD_QUEUE_KEY = "rag:upload:queue"
DELETE_QUEUE_KEY = "rag:delete:queue"
UPLOAD_DELAY_KEY = "rag:upload:delay"
DELETE_DELAY_KEY = "rag:delete:delay"


def _make_redis(upload_events=None, delete_events=None):
    """Build a FakeRedis for queue and sorted-set operations."""
    lists: dict = {}
    zsets: dict = {}

    for e in (upload_events or []):
        lists.setdefault(UPLOAD_QUEUE_KEY, []).append(json.dumps(e))
    for e in (delete_events or []):
        lists.setdefault(DELETE_QUEUE_KEY, []).append(json.dumps(e))

    class FakeRedis:
        def rpop(self, key):
            lst = lists.get(key, [])
            return lst.pop() if lst else None

        def lpush(self, key, value):
            lists.setdefault(key, []).insert(0, value)

        def zadd(self, key, mapping: dict):
            zsets.setdefault(key, {}).update(mapping)

        def zrangebyscore(self, key, min_score, max_score):
            return [m for m, s in zsets.get(key, {}).items() if min_score <= s <= max_score]

        def zrem(self, key, *members):
            zset = zsets.get(key, {})
            for m in members:
                zset.pop(m, None)

    return FakeRedis(), lists, zsets


def _fake_set_processing(doc_id, run_id=""):
    pass


def _fake_set_deleting(doc_id, run_id=""):
    pass


def test_poll_upload_not_processing_dispatches():
    """Upload event, doc not processing -> _run_ingest task created."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _, zsets = _make_redis(upload_events=[{"doc_id": DOC_ID, "force": False}])
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with (
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value=None),
        patch("rag_api.pipeline.ops.meta.set_processing", side_effect=_fake_set_processing),
        patch("asyncio.create_task", side_effect=fake_create_task),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        asyncio.run(worker._poll())

    assert any("_run_ingest" in d for d in dispatched)
    assert UPLOAD_DELAY_KEY not in zsets


def test_poll_upload_while_processing_delays():
    """Upload event, doc is running -> zadd to upload delay sorted set."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _, zsets = _make_redis(upload_events=[{"doc_id": DOC_ID, "force": False}])

    with (
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running"}),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        asyncio.run(worker._poll())

    assert len(zsets.get(UPLOAD_DELAY_KEY, {})) == 1
    assert UPLOAD_QUEUE_KEY not in zsets


def test_poll_delete_not_processing_dispatches():
    """Delete event, doc not processing -> _run_delete task created."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _, zsets = _make_redis(delete_events=[{"doc_id": DOC_ID}])
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro))
        coro.close()
        return MagicMock()

    with (
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value=None),
        patch("rag_api.pipeline.ops.meta.set_deleting", side_effect=_fake_set_deleting),
        patch("asyncio.create_task", side_effect=fake_create_task),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        asyncio.run(worker._poll())

    assert any("_run_delete" in d for d in dispatched)
    assert DELETE_DELAY_KEY not in zsets


def test_poll_delete_while_processing_delays():
    """Delete event, doc is running -> zadd to delete delay sorted set."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _, zsets = _make_redis(delete_events=[{"doc_id": DOC_ID}])

    with (
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running"}),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        asyncio.run(worker._poll())

    assert len(zsets.get(DELETE_DELAY_KEY, {})) == 1


def test_poll_upload_while_deleting_delays():
    """Upload event, doc is deleting -> delayed (added to delay queue, no dispatch)."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _, zsets = _make_redis(upload_events=[{"doc_id": DOC_ID, "force": False}])
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro)
        coro.close()
        return MagicMock()

    with (
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "deleting"}),
        patch("asyncio.create_task", side_effect=fake_create_task),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        asyncio.run(worker._poll())

    assert len(zsets.get(UPLOAD_DELAY_KEY, {})) == 1
    assert len(dispatched) == 0


def test_poll_delete_while_deleting_dispatched():
    """Delete event, doc is already in deleting state -> still dispatched (no guard)."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    fake_redis, _, zsets = _make_redis(delete_events=[{"doc_id": DOC_ID}])
    dispatched = []

    def fake_create_task(coro, **kw):
        dispatched.append(coro)
        coro.close()
        return MagicMock()

    with (
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "deleting"}),
        patch("asyncio.create_task", side_effect=fake_create_task),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        asyncio.run(worker._poll())

    assert len(zsets.get(DELETE_DELAY_KEY, {})) == 0
    assert len(dispatched) == 1


def test_duplicate_delay_overwrites_not_accumulates():
    """Same doc_id blocked twice -> only one entry in delay sorted set (overwrite)."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    worker = QueueWorker()
    worker._semaphore = asyncio.Semaphore(4)

    raw = json.dumps({"doc_id": DOC_ID, "force": False})
    fake_redis, _, zsets = _make_redis(upload_events=[
        {"doc_id": DOC_ID, "force": False},
        {"doc_id": DOC_ID, "force": False},
    ])

    with (
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running"}),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        asyncio.run(worker._poll())

    assert len(zsets.get(UPLOAD_DELAY_KEY, {})) == 1


def test_poll_upload_fills_limit_delete_still_runs():
    """Upload queue at max_per_poll capacity -> delete queue is still processed independently."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    max_per_poll = 5
    worker = QueueWorker(max_per_poll=max_per_poll)
    worker._semaphore = asyncio.Semaphore(10)

    upload_events = [{"doc_id": f"00000000-0000-0000-0000-{i:012d}", "force": False} for i in range(max_per_poll)]
    delete_events = [{"doc_id": f"99999999-0000-0000-0000-{i:012d}"} for i in range(3)]
    fake_redis, _, _ = _make_redis(upload_events=upload_events, delete_events=delete_events)

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
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value=None),
        patch("rag_api.pipeline.ops.meta.set_processing", side_effect=_fake_set_processing),
        patch("rag_api.pipeline.ops.meta.set_deleting", side_effect=_fake_set_deleting),
        patch("asyncio.create_task", side_effect=fake_create_task),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        asyncio.run(worker._poll())

    assert len(ingest_dispatched) == max_per_poll
    assert len(delete_dispatched) == 3


def test_poll_returns_true_when_upload_hits_limit():
    """_poll returns True when upload queue reaches max_per_poll."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    max_per_poll = 5
    worker = QueueWorker(max_per_poll=max_per_poll)
    worker._semaphore = asyncio.Semaphore(10)

    upload_events = [{"doc_id": f"00000000-0000-0000-0000-{i:012d}", "force": False} for i in range(max_per_poll)]
    fake_redis, _, _ = _make_redis(upload_events=upload_events)

    def fake_create_task(coro, **kw):
        coro.close()
        return MagicMock()

    with (
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value=None),
        patch("rag_api.pipeline.ops.meta.set_processing", side_effect=_fake_set_processing),
        patch("asyncio.create_task", side_effect=fake_create_task),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        result = asyncio.run(worker._poll())

    assert result is True


def test_poll_returns_false_when_queues_drained():
    """_poll returns False when both queues exhaust before hitting max_per_poll."""
    from rag_api.pipeline.queue.queue_worker import QueueWorker

    worker = QueueWorker(max_per_poll=5)
    worker._semaphore = asyncio.Semaphore(10)

    upload_events = [{"doc_id": f"00000000-0000-0000-0000-{i:012d}", "force": False} for i in range(3)]
    delete_events = [{"doc_id": f"99999999-0000-0000-0000-{i:012d}"} for i in range(2)]
    fake_redis, _, _ = _make_redis(upload_events=upload_events, delete_events=delete_events)

    def fake_create_task(coro, **kw):
        coro.close()
        return MagicMock()

    with (
        patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        patch("rag_api.infra.postgres.get_doc_by_id", return_value=None),
        patch("rag_api.pipeline.ops.meta.set_processing", side_effect=_fake_set_processing),
        patch("rag_api.pipeline.ops.meta.set_deleting", side_effect=_fake_set_deleting),
        patch("asyncio.create_task", side_effect=fake_create_task),
        patch("rag_api.config.settings.get_settings") as mock_cfg,
    ):
        mock_cfg.return_value.queue_poll.retry_interval_sec = 30
        result = asyncio.run(worker._poll())

    assert result is False


def test_drain_delay_queue_moves_ready_items():
    """_drain_delay_queue moves items with score <= now to main queue."""
    from rag_api.pipeline.queue.queue_worker import _drain_delay_queue

    _, lists, zsets = _make_redis()

    class FakeRedis:
        def rpop(self, key):
            lst = lists.get(key, [])
            return lst.pop() if lst else None

        def lpush(self, key, value):
            lists.setdefault(key, []).insert(0, value)

        def zadd(self, key, mapping):
            zsets.setdefault(key, {}).update(mapping)

        def zrangebyscore(self, key, min_score, max_score):
            return [m for m, s in zsets.get(key, {}).items() if min_score <= s <= max_score]

        def zrem(self, key, *members):
            zset = zsets.get(key, {})
            for m in members:
                zset.pop(m, None)

    r = FakeRedis()
    raw = json.dumps({"doc_id": DOC_ID, "force": False})
    r.zadd(UPLOAD_DELAY_KEY, {raw: time.time() - 1})  # already ready

    with (
        patch("rag_api.infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "status": "pending"}),
        patch("rag_api.infra.postgres.update_doc_fields"),
    ):
        _drain_delay_queue(r, UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY)

    assert len(zsets.get(UPLOAD_DELAY_KEY, {})) == 0
    assert UPLOAD_QUEUE_KEY in lists
    assert len(lists[UPLOAD_QUEUE_KEY]) == 1


def test_drain_delay_queue_skips_future_items():
    """_drain_delay_queue does not move items with score > now."""
    from rag_api.pipeline.queue.queue_worker import _drain_delay_queue

    _, lists, zsets = _make_redis()

    class FakeRedis:
        def lpush(self, key, value):
            lists.setdefault(key, []).insert(0, value)

        def zadd(self, key, mapping):
            zsets.setdefault(key, {}).update(mapping)

        def zrangebyscore(self, key, min_score, max_score):
            return [m for m, s in zsets.get(key, {}).items() if min_score <= s <= max_score]

        def zrem(self, key, *members):
            pass

    r = FakeRedis()
    raw = json.dumps({"doc_id": DOC_ID, "force": False})
    r.zadd(UPLOAD_DELAY_KEY, {raw: time.time() + 9999})  # not ready yet

    _drain_delay_queue(r, UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY)

    assert UPLOAD_QUEUE_KEY not in lists
    assert len(zsets.get(UPLOAD_DELAY_KEY, {})) == 1
