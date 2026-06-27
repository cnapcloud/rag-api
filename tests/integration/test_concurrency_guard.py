"""Concurrency guard acceptance tests.

Verifies the two bidirectional delay scenarios from US-02:
  AC-1: ingest in progress  -> delete request is delayed
  AC-2: delete in progress  -> ingest request is delayed

Each scenario is tested in both dispatch modes:
  - Dagster sensor (event_queue_sensor)
  - QueueWorker (_poll)
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import MagicMock, patch

DOC_ID = "11111111-1111-1111-1111-111111111111"


# ─────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────

class FakeRedis:
    def __init__(self):
        self._lists: dict[str, list] = {}
        self._docs: dict[str, dict] = {}
        self._zsets: dict[str, dict] = {}

    def rpop(self, key):
        lst = self._lists.get(key, [])
        return lst.pop() if lst else None

    def lpush(self, key, *values):
        self._lists.setdefault(key, [])
        for v in values:
            self._lists[key].insert(0, v)

    def zadd(self, key, mapping: dict):
        self._zsets.setdefault(key, {}).update(mapping)

    def zrangebyscore(self, key, min_s, max_s):
        return [m for m, s in self._zsets.get(key, {}).items() if min_s <= s <= max_s]

    def zrem(self, key, *members):
        zset = self._zsets.get(key, {})
        for m in members:
            zset.pop(m, None)

    def get(self, key):
        return None

    def set(self, key, value):
        pass

    # helpers
    def set_doc(self, doc_id: str, status: str, run_id: str = "") -> None:
        self._docs[doc_id] = {"doc_id": doc_id, "kb_id": "kb-1", "status": status, "run_id": run_id}

    def get_doc(self, doc_id: str) -> dict | None:
        return self._docs.get(doc_id)

    def upload_queue_size(self):
        return len(self._lists.get("rag:upload:queue", []))

    def delete_queue_size(self):
        return len(self._lists.get("rag:delete:queue", []))

    def upload_delay_size(self):
        return len(self._zsets.get("rag:upload:delay", {}))

    def delete_delay_size(self):
        return len(self._zsets.get("rag:delete:delay", {}))


def _run_sensor(fake_redis, get_run_by_id=None):
    from contextlib import ExitStack
    from unittest.mock import MagicMock, PropertyMock

    from dagster import RunRequest, build_sensor_context
    from defs.sensors.event_queue_sensor import event_queue_sensor

    mock_settings = MagicMock()
    mock_settings.queue_worker.enabled = False

    ctx = build_sensor_context()
    with ExitStack() as stack:
        stack.enter_context(patch("infra.redis.get_redis_client", return_value=fake_redis))
        stack.enter_context(patch("defs.sensors.event_queue_sensor._get_settings", return_value=mock_settings))
        stack.enter_context(
            patch("infra.postgres.get_doc_by_id", side_effect=lambda doc_id: fake_redis.get_doc(doc_id))
        )
        stack.enter_context(patch("infra.postgres.update_doc_fields"))
        stack.enter_context(patch("pipeline.ops.meta.update_doc_fields"))
        if get_run_by_id is not None:
            mock_instance = MagicMock()
            mock_instance.get_run_by_id.side_effect = get_run_by_id
            stack.enter_context(patch.object(type(ctx), "instance", new_callable=PropertyMock, return_value=mock_instance))
        return [r for r in event_queue_sensor(ctx) if isinstance(r, RunRequest)]


# ─────────────────────────────────────────────────────────────
# Sensor mode
# ─────────────────────────────────────────────────────────────

class TestSensorConcurrencyGuard:

    def test_ac1_delete_delayed_while_ingest_processing(self):
        """AC-1 (sensor): ingest processing -> delete request delayed, no RunRequest."""
        active_run = MagicMock()
        active_run.is_finished = False

        r = FakeRedis()
        r.lpush("rag:delete:queue", json.dumps({"doc_id": DOC_ID}))
        r.set_doc(DOC_ID, "running", run_id="run-ingest-active")

        result = _run_sensor(r, get_run_by_id=lambda _: active_run)

        assert result == [], "delete RunRequest should not be emitted while ingest is running"
        assert r.delete_delay_size() == 1, "delete event should be in delay queue"
        assert r.delete_queue_size() == 0, "delete event should be removed from main queue"

    def test_ac2_ingest_delayed_while_delete_running(self):
        """AC-2 (sensor): delete in progress -> ingest request delayed, no RunRequest."""
        active_run = MagicMock()
        active_run.is_finished = False

        r = FakeRedis()
        r.lpush("rag:upload:queue", json.dumps({"doc_id": DOC_ID, "force": False}))
        r.set_doc(DOC_ID, "deleting", run_id="run-delete-active")

        result = _run_sensor(r, get_run_by_id=lambda _: active_run)

        assert result == [], "ingest RunRequest should not be emitted while delete is running"
        assert r.upload_delay_size() == 1, "upload event should be in delay queue"
        assert r.upload_queue_size() == 0, "upload event should be removed from main queue"

    def test_ac1_delete_proceeds_after_ingest_completes(self):
        """AC-1 follow-up (sensor): ingest completed (indexed) -> delete dispatched normally."""
        r = FakeRedis()
        r.lpush("rag:delete:queue", json.dumps({"doc_id": DOC_ID}))
        r.set_doc(DOC_ID, "indexed")

        result = _run_sensor(r)

        assert len(result) == 1
        assert result[0].job_name == "delete_job"
        assert r.delete_delay_size() == 0

    def test_ac2_ingest_proceeds_after_delete_completes(self):
        """AC-2 follow-up (sensor): delete completed (doc gone) -> ingest dispatched normally."""
        r = FakeRedis()
        r.lpush("rag:upload:queue", json.dumps({"doc_id": DOC_ID, "force": False}))
        # No doc in store -> delete completed

        result = _run_sensor(r)

        assert len(result) == 1
        assert result[0].job_name == "ingest_job"
        assert r.upload_delay_size() == 0


# ─────────────────────────────────────────────────────────────
# QueueWorker mode
# ─────────────────────────────────────────────────────────────

class TestQueueWorkerConcurrencyGuard:

    def _run_poll(self, fake_redis):
        from pipeline.queue_worker import QueueWorker

        worker = QueueWorker()
        worker._semaphore = asyncio.Semaphore(4)
        dispatched: list[str] = []

        def fake_create_task(coro, **kw):
            name = coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro)
            dispatched.append(name)
            coro.close()
            return MagicMock()

        with (
            patch("infra.redis.get_redis_client", return_value=fake_redis),
            patch("infra.postgres.get_doc_by_id", side_effect=lambda doc_id: fake_redis.get_doc(doc_id)),
            patch("infra.postgres.update_doc_fields"),
            patch("pipeline.ops.meta.update_doc_fields"),
            patch("asyncio.create_task", side_effect=fake_create_task),
            patch("config.settings.get_settings") as mock_cfg,
        ):
            mock_cfg.return_value.queue_poll.retry_interval_sec = 30
            asyncio.run(worker._poll())

        return dispatched

    def test_ac1_delete_delayed_while_ingest_processing(self):
        """AC-1 (QueueWorker): ingest processing -> zadd to delete delay, _run_delete not dispatched."""
        r = FakeRedis()
        r.lpush("rag:delete:queue", json.dumps({"doc_id": DOC_ID}))
        r.set_doc(DOC_ID, "running")

        dispatched = self._run_poll(r)

        assert not any("_run_delete" in d for d in dispatched), \
            "delete task should not be dispatched while ingest is running"
        assert r.delete_delay_size() == 1, "delete event should be in delay sorted set"

    def test_ac2_ingest_delayed_while_delete_running(self):
        """AC-2 (QueueWorker): delete in progress -> zadd to upload delay, _run_ingest not dispatched."""
        r = FakeRedis()
        r.lpush("rag:upload:queue", json.dumps({"doc_id": DOC_ID, "force": False}))
        r.set_doc(DOC_ID, "deleting")

        dispatched = self._run_poll(r)

        assert not any("_run_ingest" in d for d in dispatched), \
            "ingest task should not be dispatched while delete is running"
        assert r.upload_delay_size() == 1, "upload event should be in delay sorted set"

    def test_ac1_delete_proceeds_after_ingest_completes(self):
        """AC-1 follow-up (QueueWorker): ingest completed -> _run_delete dispatched."""
        r = FakeRedis()
        r.lpush("rag:delete:queue", json.dumps({"doc_id": DOC_ID}))
        r.set_doc(DOC_ID, "indexed")

        dispatched = self._run_poll(r)

        assert any("_run_delete" in d for d in dispatched)
        assert r.delete_delay_size() == 0

    def test_ac2_ingest_proceeds_after_delete_completes(self):
        """AC-2 follow-up (QueueWorker): delete completed (doc gone) -> _run_ingest dispatched."""
        r = FakeRedis()
        r.lpush("rag:upload:queue", json.dumps({"doc_id": DOC_ID, "force": False}))
        # No doc in store -> not blocked

        dispatched = self._run_poll(r)

        assert any("_run_ingest" in d for d in dispatched)
        assert r.upload_delay_size() == 0
