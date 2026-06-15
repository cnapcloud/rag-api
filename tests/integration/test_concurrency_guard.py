"""Concurrency guard acceptance tests.

Verifies the two bidirectional delay scenarios from US-02:
  AC-1: ingest in progress  → delete request is delayed
  AC-2: delete in progress  → ingest request is delayed

Each scenario is tested in both dispatch modes:
  - Dagster sensor (event_queue_sensor)
  - QueueWorker (_poll)
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────

class FakeRedis:
    def __init__(self):
        self._lists: dict[str, list] = {}
        self._hashes: dict[str, dict] = {}
        self._sets: dict[str, set] = {}
        self._zsets: dict[str, dict] = {}

    def rpop(self, key):
        lst = self._lists.get(key, [])
        return lst.pop() if lst else None

    def lpush(self, key, *values):
        self._lists.setdefault(key, [])
        for v in values:
            self._lists[key].insert(0, v)

    def hset(self, key, mapping=None, **kw):
        self._hashes.setdefault(key, {}).update(
            {k: str(v) for k, v in (mapping or {}).items()}
        )

    def hsetnx(self, key, field, value):
        self._hashes.setdefault(key, {})
        if field not in self._hashes[key]:
            self._hashes[key][field] = str(value)

    def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    def sadd(self, key, *values):
        self._sets.setdefault(key, set()).update(values)

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
    def set_doc_status(self, kb_id, object_key, status):
        self._hashes[f"doc:{kb_id}:{object_key}"] = {"status": status}

    def upload_queue_size(self):
        return len(self._lists.get("rag:upload:queue", []))

    def delete_queue_size(self):
        return len(self._lists.get("rag:delete:queue", []))

    def upload_delay_size(self):
        return len(self._zsets.get("rag:upload:delay", {}))

    def delete_delay_size(self):
        return len(self._zsets.get("rag:delete:delay", {}))


def _run_sensor(fake_redis):
    from unittest.mock import MagicMock

    from dagster import RunRequest, build_sensor_context
    from dagster_pipeline.sensors.event_queue_sensor import event_queue_sensor

    mock_settings = MagicMock()
    mock_settings.queue_worker.enabled = False

    ctx = build_sensor_context()
    with (
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("dagster_pipeline.sensors.event_queue_sensor._get_settings", return_value=mock_settings),
    ):
        return [r for r in event_queue_sensor(ctx) if isinstance(r, RunRequest)]


# ─────────────────────────────────────────────────────────────
# Sensor mode
# ─────────────────────────────────────────────────────────────

class TestSensorConcurrencyGuard:

    def test_ac1_delete_delayed_while_ingest_processing(self):
        """AC-1 (sensor): ingest processing 중 delete 요청 → delay 큐, RunRequest 없음."""
        r = FakeRedis()
        r.lpush("rag:delete:queue", json.dumps({"kb_id": "kb-1", "object_key": "doc.pdf"}))
        r.set_doc_status("kb-1", "doc.pdf", "running")  # ingest 진행 중

        result = _run_sensor(r)

        assert result == [], "delete RunRequest should not be emitted while ingest is running"
        assert r.delete_delay_size() == 1, "delete event should be in delay queue"
        assert r.delete_queue_size() == 0, "delete event should be removed from main queue"

    def test_ac2_ingest_delayed_while_delete_running(self):
        """AC-2 (sensor): delete 진행 중 ingest 요청 → delay 큐, RunRequest 없음."""
        r = FakeRedis()
        r.lpush("rag:upload:queue", json.dumps(
            {"kb_id": "kb-1", "object_key": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}
        ))
        r.set_doc_status("kb-1", "doc.pdf", "deleting")  # delete 진행 중

        result = _run_sensor(r)

        assert result == [], "ingest RunRequest should not be emitted while delete is running"
        assert r.upload_delay_size() == 1, "upload event should be in delay queue"
        assert r.upload_queue_size() == 0, "upload event should be removed from main queue"

    def test_ac1_delete_proceeds_after_ingest_completes(self):
        """AC-1 follow-up (sensor): ingest 완료(indexed) 후 delete → 정상 dispatch."""
        r = FakeRedis()
        r.lpush("rag:delete:queue", json.dumps({"kb_id": "kb-1", "object_key": "doc.pdf"}))
        r.set_doc_status("kb-1", "doc.pdf", "indexed")  # ingest 완료 상태

        result = _run_sensor(r)

        assert len(result) == 1
        assert result[0].job_name == "delete_job"
        assert r.delete_delay_size() == 0

    def test_ac2_ingest_proceeds_after_delete_completes(self):
        """AC-2 follow-up (sensor): delete 완료(메타 없음) 후 ingest → 정상 dispatch."""
        r = FakeRedis()
        r.lpush("rag:upload:queue", json.dumps(
            {"kb_id": "kb-1", "object_key": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}
        ))
        # delete 완료 → 메타 없음 (doc hash 자체가 존재하지 않음)

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
        requeued: list[str] = []

        def fake_create_task(coro, **kw):
            name = coro.__qualname__ if hasattr(coro, "__qualname__") else str(coro)
            if "_requeue_after_delay" in name:
                requeued.append(name)
            else:
                dispatched.append(name)
            coro.close()
            return MagicMock()

        with patch("infra.redis.get_redis_client", return_value=fake_redis):
            with patch("asyncio.create_task", side_effect=fake_create_task):
                asyncio.run(worker._poll())

        return dispatched, requeued

    def test_ac1_delete_delayed_while_ingest_processing(self):
        """AC-1 (QueueWorker): ingest processing 중 delete 요청 → requeue, _run_delete 없음."""
        r = FakeRedis()
        r.lpush("rag:delete:queue", json.dumps({"kb_id": "kb-1", "object_key": "doc.pdf"}))
        r.set_doc_status("kb-1", "doc.pdf", "running")

        dispatched, requeued = self._run_poll(r)

        assert not any("_run_delete" in d for d in dispatched), \
            "delete task should not be dispatched while ingest is running"
        assert len(requeued) == 1, "delete event should be requeued for later"

    def test_ac2_ingest_delayed_while_delete_running(self):
        """AC-2 (QueueWorker): delete 진행 중 ingest 요청 → requeue, _run_ingest 없음."""
        r = FakeRedis()
        r.lpush("rag:upload:queue", json.dumps(
            {"kb_id": "kb-1", "object_key": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}
        ))
        r.set_doc_status("kb-1", "doc.pdf", "deleting")

        dispatched, requeued = self._run_poll(r)

        assert not any("_run_ingest" in d for d in dispatched), \
            "ingest task should not be dispatched while delete is running"
        assert len(requeued) == 1, "upload event should be requeued for later"

    def test_ac1_delete_proceeds_after_ingest_completes(self):
        """AC-1 follow-up (QueueWorker): ingest 완료 후 delete → _run_delete dispatch."""
        r = FakeRedis()
        r.lpush("rag:delete:queue", json.dumps({"kb_id": "kb-1", "object_key": "doc.pdf"}))
        r.set_doc_status("kb-1", "doc.pdf", "indexed")

        dispatched, requeued = self._run_poll(r)

        assert any("_run_delete" in d for d in dispatched)
        assert len(requeued) == 0

    def test_ac2_ingest_proceeds_after_delete_completes(self):
        """AC-2 follow-up (QueueWorker): delete 완료(메타 없음) 후 ingest → _run_ingest dispatch."""
        r = FakeRedis()
        r.lpush("rag:upload:queue", json.dumps(
            {"kb_id": "kb-1", "object_key": "doc.pdf", "etag": "e1", "file_size": 0, "force": False}
        ))
        # 메타 없음 → is_doc_busy() False

        dispatched, requeued = self._run_poll(r)

        assert any("_run_ingest" in d for d in dispatched)
        assert len(requeued) == 0
