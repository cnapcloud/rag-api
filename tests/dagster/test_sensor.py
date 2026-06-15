"""event_queue_sensor unit tests."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch


class FakeRedis:
    """Full-featured fake Redis for sensor tests."""

    def __init__(self):
        self._lists: dict[str, list] = {}
        self._hashes: dict[str, dict] = {}
        self._sets: dict[str, set] = {}
        self._zsets: dict[str, dict] = {}  # key → {member: score}
        self._strings: dict[str, str] = {}

    # list
    def rpop(self, key: str):
        lst = self._lists.get(key, [])
        return lst.pop() if lst else None

    def lpush(self, key: str, *values):
        if key not in self._lists:
            self._lists[key] = []
        for v in values:
            self._lists[key].insert(0, v)

    # hash
    def hset(self, key, mapping=None, **kw):
        if key not in self._hashes:
            self._hashes[key] = {}
        if mapping:
            self._hashes[key].update({k: str(v) for k, v in mapping.items()})

    def hsetnx(self, key, field, value):
        self._hashes.setdefault(key, {})
        if field not in self._hashes[key]:
            self._hashes[key][field] = str(value)

    def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    # set
    def sadd(self, key, *values):
        self._sets.setdefault(key, set()).update(values)

    # sorted set
    def zadd(self, key, mapping: dict):
        if key not in self._zsets:
            self._zsets[key] = {}
        self._zsets[key].update(mapping)

    def zrangebyscore(self, key, min_score, max_score):
        zset = self._zsets.get(key, {})
        return [m for m, s in zset.items() if min_score <= s <= max_score]

    def zrem(self, key, *members):
        zset = self._zsets.get(key, {})
        for m in members:
            zset.pop(m, None)

    # string
    def get(self, key):
        return self._strings.get(key)

    def set(self, key, value):
        self._strings[key] = value


def _make_redis(
    put_events: list[dict] | None = None,
    delete_events: list[dict] | None = None,
    processing_keys: list[tuple[str, str]] | None = None,
) -> FakeRedis:
    r = FakeRedis()
    for e in (put_events or []):
        r.lpush("rag:upload:queue", json.dumps(e))
    for e in (delete_events or []):
        r.lpush("rag:delete:queue", json.dumps(e))
    for kb_id, object_key in (processing_keys or []):
        r.hset(f"doc:{kb_id}:{object_key}", mapping={"status": "running"})
    return r


def _run_sensor(fake_redis, get_run_by_id=None, set_failed_calls=None):
    from contextlib import ExitStack
    from unittest.mock import MagicMock, PropertyMock, patch

    from dagster import RunRequest, build_sensor_context
    from dagster_pipeline.sensors.event_queue_sensor import event_queue_sensor

    mock_settings = MagicMock()
    mock_settings.queue_worker.enabled = False

    ctx = build_sensor_context()
    with ExitStack() as stack:
        stack.enter_context(patch("infra.redis.get_redis_client", return_value=fake_redis))
        stack.enter_context(patch("dagster_pipeline.sensors.event_queue_sensor._get_settings", return_value=mock_settings))
        if get_run_by_id is not None:
            mock_instance = MagicMock()
            mock_instance.get_run_by_id.side_effect = get_run_by_id
            stack.enter_context(patch.object(type(ctx), "instance", new_callable=PropertyMock, return_value=mock_instance))
        if set_failed_calls is not None:
            stack.enter_context(
                patch("pipeline.ops.meta.set_failed", side_effect=lambda kb, key, err, run_id="": set_failed_calls.append((kb, key, run_id)))
            )
        return [r for r in event_queue_sensor(ctx) if isinstance(r, RunRequest)]


def test_upload_sensor_put_generates_ingest_run():
    """PUT event → ingest_job RunRequest with UUID run_key."""
    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "etag-001", "file_size": 1024, "force": False}
    ])
    result = _run_sensor(fake_redis)

    assert len(result) == 1
    req = result[0]
    assert req.job_name == "ingest_job"
    assert req.tags.get("kb_id") == "kb-test"
    assert req.run_key  # UUID — non-empty
    cfg = req.run_config["ops"]["validate_op"]["config"]
    assert cfg["kb_id"] == "kb-test"
    assert cfg["object_key"] == "doc.pdf"
    assert cfg["force"] is False


def test_upload_sensor_delete_generates_delete_run():
    """DELETE event → delete_job RunRequest with UUID run_key."""
    fake_redis = _make_redis(delete_events=[
        {"kb_id": "kb-test", "object_key": "doc.pdf"}
    ])
    result = _run_sensor(fake_redis)

    assert len(result) == 1
    req = result[0]
    assert req.job_name == "delete_job"
    assert req.tags.get("kb_id") == "kb-test"
    assert req.run_key  # UUID — non-empty


def test_upload_sensor_no_events():
    """Empty queues → no RunRequests."""
    fake_redis = _make_redis()
    result = _run_sensor(fake_redis)
    assert result == []


def test_upload_sensor_batch_put():
    """Multiple PUT events → all consumed in one sensor tick."""
    events = [
        {"kb_id": "kb-test", "object_key": f"doc{i}.pdf", "etag": f"etag-{i:03d}", "file_size": 0, "force": False}
        for i in range(5)
    ]
    fake_redis = _make_redis(put_events=events)
    result = _run_sensor(fake_redis)

    assert len(result) == 5
    assert all(r.job_name == "ingest_job" for r in result)


def test_upload_sensor_mixed_queues():
    """PUT and DELETE events consumed together in one tick."""
    fake_redis = _make_redis(
        put_events=[{"kb_id": "kb-test", "object_key": "new.pdf", "etag": "etag-new", "file_size": 0, "force": False}],
        delete_events=[{"kb_id": "kb-test", "object_key": "old.pdf"}],
    )
    result = _run_sensor(fake_redis)

    assert len(result) == 2
    job_names = {r.job_name for r in result}
    assert "ingest_job" in job_names
    assert "delete_job" in job_names


def test_upload_sensor_force_flag_propagated():
    """force=True in PUT event → run_config carries force=True."""
    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": True}
    ])
    result = _run_sensor(fake_redis)

    assert len(result) == 1
    cfg = result[0].run_config["ops"]["validate_op"]["config"]
    assert cfg["force"] is True


def test_sensor_upload_skips_processing_doc():
    """Upload event: doc is actively running (Dagster run alive) → delayed, no RunRequest."""
    active_run = MagicMock()
    active_run.is_finished = False

    fake_redis = _make_redis(
        put_events=[{"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}],
    )
    fake_redis.hset("doc:kb-test:doc.pdf", mapping={"status": "running", "run_id": "run-active"})

    result = _run_sensor(fake_redis, get_run_by_id=lambda _: active_run)

    assert result == []
    assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 1


def test_sensor_upload_zombie_run_dispatches():
    """Upload event: doc has status=running but Dagster run is finished → zombie recovered, dispatched."""
    dead_run = MagicMock()
    dead_run.is_finished = True

    fake_redis = _make_redis(
        put_events=[{"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}],
    )
    fake_redis.hset("doc:kb-test:doc.pdf", mapping={"status": "running", "run_id": "run-dead"})

    calls = []
    result = _run_sensor(fake_redis, get_run_by_id=lambda _: dead_run, set_failed_calls=calls)

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"
    assert len(calls) == 1
    assert calls[0][2] == "run-dead"


def test_sensor_upload_run_not_found_dispatches():
    """Upload event: doc has run_id but Dagster returns None → zombie recovered, dispatched."""
    fake_redis = _make_redis(
        put_events=[{"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}],
    )
    fake_redis.hset("doc:kb-test:doc.pdf", mapping={"status": "running", "run_id": "run-ghost"})

    calls = []
    result = _run_sensor(fake_redis, get_run_by_id=lambda _: None, set_failed_calls=calls)

    assert len(result) == 1
    assert len(calls) == 1
    assert calls[0][2] == "run-ghost"


def test_sensor_upload_dispatch_lock_remnant_dispatches():
    """Upload event: status=running with no run_id (dispatch lock remnant) → dispatch immediately."""
    fake_redis = _make_redis(
        put_events=[{"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}],
        processing_keys=[("kb-test", "doc.pdf")],  # sets status=running, run_id absent
    )
    result = _run_sensor(fake_redis)

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"


def test_sensor_upload_skips_deleting_doc():
    """Upload event: doc is deleting → delayed, no RunRequest."""
    fake_redis = _make_redis(
        put_events=[{"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}],
    )
    fake_redis.hset("doc:kb-test:doc.pdf", mapping={"status": "deleting"})
    result = _run_sensor(fake_redis)

    assert result == []
    assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 1


def test_sensor_delete_skips_processing_doc():
    """Delete event: doc is processing → delayed, no RunRequest."""
    fake_redis = _make_redis(
        delete_events=[{"kb_id": "kb-test", "object_key": "doc.pdf"}],
        processing_keys=[("kb-test", "doc.pdf")],
    )
    result = _run_sensor(fake_redis)

    assert result == []
    assert len(fake_redis._zsets.get("rag:delete:delay", {})) == 1


def test_sensor_delete_skips_deleting_doc():
    """Delete event: doc is already deleting → delayed, no RunRequest."""
    fake_redis = _make_redis(
        delete_events=[{"kb_id": "kb-test", "object_key": "doc.pdf"}],
    )
    fake_redis.hset("doc:kb-test:doc.pdf", mapping={"status": "deleting"})
    result = _run_sensor(fake_redis)

    assert result == []
    assert len(fake_redis._zsets.get("rag:delete:delay", {})) == 1


def test_sensor_drain_delay_queue():
    """Ready item in delay queue is moved to main queue and dispatched."""
    raw = json.dumps({"kb_id": "kb-test", "object_key": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False})
    fake_redis = FakeRedis()
    # Pre-load into delay queue with score in the past (already ready)
    fake_redis.zadd("rag:upload:delay", {raw: time.time() - 1})

    result = _run_sensor(fake_redis)

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"
    assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 0


def test_sensor_run_keys_unique():
    """Two events in one tick → two different run_keys."""
    events = [
        {"kb_id": "kb-test", "object_key": "a.pdf", "etag": "e1", "file_size": 0, "force": False},
        {"kb_id": "kb-test", "object_key": "b.pdf", "etag": "e2", "file_size": 0, "force": False},
    ]
    fake_redis = _make_redis(put_events=events)
    result = _run_sensor(fake_redis)

    assert len(result) == 2
    assert result[0].run_key != result[1].run_key
