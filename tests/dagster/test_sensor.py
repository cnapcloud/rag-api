"""event_queue_sensor unit tests."""

from __future__ import annotations

import json
import time
from contextlib import ExitStack
from unittest.mock import MagicMock, PropertyMock, patch


class FakeRedis:
    """Fake Redis for sensor tests — queue and sorted-set operations only."""

    def __init__(self):
        self._lists: dict[str, list] = {}
        self._zsets: dict[str, dict] = {}

    def rpop(self, key: str):
        lst = self._lists.get(key, [])
        return lst.pop() if lst else None

    def lpush(self, key: str, *values):
        if key not in self._lists:
            self._lists[key] = []
        for v in values:
            self._lists[key].insert(0, v)

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


def _make_redis(
    put_events: list[dict] | None = None,
    delete_events: list[dict] | None = None,
) -> FakeRedis:
    r = FakeRedis()
    for e in (put_events or []):
        r.lpush("rag:upload:queue", json.dumps(e))
    for e in (delete_events or []):
        r.lpush("rag:delete:queue", json.dumps(e))
    return r


def _run_sensor(
    fake_redis: FakeRedis,
    pg_doc_status=None,
    get_run_by_id=None,
    set_failed_calls=None,
):
    """Execute the sensor once and return RunRequest objects.

    pg_doc_status: value returned by infra.postgres.get_doc_status (None or dict).
    """
    from dagster import RunRequest, build_sensor_context
    from dagster_pipeline.sensors.event_queue_sensor import event_queue_sensor

    mock_settings = MagicMock()
    mock_settings.queue_worker.enabled = False

    ctx = build_sensor_context()
    with ExitStack() as stack:
        stack.enter_context(patch("infra.redis.get_redis_client", return_value=fake_redis))
        stack.enter_context(
            patch("dagster_pipeline.sensors.event_queue_sensor._get_settings", return_value=mock_settings)
        )
        stack.enter_context(patch("infra.postgres.get_doc_status", return_value=pg_doc_status))
        stack.enter_context(patch("infra.postgres.set_doc_status"))
        if get_run_by_id is not None:
            mock_instance = MagicMock()
            mock_instance.get_run_by_id.side_effect = get_run_by_id
            stack.enter_context(
                patch.object(type(ctx), "instance", new_callable=PropertyMock, return_value=mock_instance)
            )
        if set_failed_calls is not None:
            stack.enter_context(
                patch(
                    "pipeline.ops.meta.set_failed",
                    side_effect=lambda kb, key, err, run_id="": set_failed_calls.append((kb, key, run_id)),
                )
            )
        return [r for r in event_queue_sensor(ctx) if isinstance(r, RunRequest)]


def test_upload_sensor_put_generates_ingest_run():
    """PUT event -> ingest_job RunRequest with UUID run_key."""
    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 1024, "force": False}
    ])
    result = _run_sensor(fake_redis)

    assert len(result) == 1
    req = result[0]
    assert req.job_name == "ingest_job"
    assert req.tags.get("kb_id") == "kb-test"
    assert req.run_key
    cfg = req.run_config["ops"]["validate_op"]["config"]
    assert cfg["kb_id"] == "kb-test"
    assert cfg["doc_source"] == "doc.pdf"
    assert cfg["force"] is False


def test_upload_sensor_delete_generates_delete_run():
    """DELETE event -> delete_job RunRequest with UUID run_key."""
    fake_redis = _make_redis(delete_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf"}])
    result = _run_sensor(fake_redis)

    assert len(result) == 1
    req = result[0]
    assert req.job_name == "delete_job"
    assert req.tags.get("kb_id") == "kb-test"
    assert req.run_key


def test_upload_sensor_no_events():
    """Empty queues -> no RunRequests."""
    result = _run_sensor(_make_redis())
    assert result == []


def test_upload_sensor_batch_put():
    """Multiple PUT events -> all consumed in one sensor tick."""
    events = [
        {"kb_id": "kb-test", "doc_source": f"doc{i}.pdf", "etag": f"etag-{i:03d}", "file_size": 0, "force": False}
        for i in range(5)
    ]
    result = _run_sensor(_make_redis(put_events=events))

    assert len(result) == 5
    assert all(r.job_name == "ingest_job" for r in result)


def test_upload_sensor_mixed_queues():
    """PUT and DELETE events consumed together in one tick."""
    fake_redis = _make_redis(
        put_events=[{"kb_id": "kb-test", "doc_source": "new.pdf", "etag": "etag-new", "file_size": 0, "force": False}],
        delete_events=[{"kb_id": "kb-test", "doc_source": "old.pdf"}],
    )
    result = _run_sensor(fake_redis)

    assert len(result) == 2
    job_names = {r.job_name for r in result}
    assert "ingest_job" in job_names
    assert "delete_job" in job_names


def test_upload_sensor_force_flag_propagated():
    """force=True in PUT event -> run_config carries force=True."""
    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": True}
    ])
    result = _run_sensor(fake_redis)

    assert len(result) == 1
    cfg = result[0].run_config["ops"]["validate_op"]["config"]
    assert cfg["force"] is True


def test_sensor_upload_skips_processing_doc():
    """Upload event: doc is actively running (Dagster run alive) -> delayed, no RunRequest."""
    active_run = MagicMock()
    active_run.is_finished = False

    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}
    ])
    result = _run_sensor(
        fake_redis,
        pg_doc_status={"status": "running", "run_id": "run-active"},
        get_run_by_id=lambda _: active_run,
    )

    assert result == []
    assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 1


def test_sensor_upload_zombie_run_dispatches():
    """Upload event: doc has status=running but Dagster run is finished -> zombie recovered, dispatched."""
    dead_run = MagicMock()
    dead_run.is_finished = True

    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}
    ])
    calls = []
    result = _run_sensor(
        fake_redis,
        pg_doc_status={"status": "running", "run_id": "run-dead"},
        get_run_by_id=lambda _: dead_run,
        set_failed_calls=calls,
    )

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"
    assert len(calls) == 1
    assert calls[0][2] == "run-dead"


def test_sensor_upload_run_not_found_dispatches():
    """Upload event: doc has run_id but Dagster returns None -> zombie recovered, dispatched."""
    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}
    ])
    calls = []
    result = _run_sensor(
        fake_redis,
        pg_doc_status={"status": "running", "run_id": "run-ghost"},
        get_run_by_id=lambda _: None,
        set_failed_calls=calls,
    )

    assert len(result) == 1
    assert len(calls) == 1
    assert calls[0][2] == "run-ghost"


def test_sensor_upload_dispatch_lock_remnant_dispatches():
    """Upload event: status=running with no run_id (dispatch lock remnant) -> dispatch immediately."""
    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}
    ])
    result = _run_sensor(
        fake_redis,
        pg_doc_status={"status": "running", "run_id": ""},
    )

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"


def test_sensor_upload_deleting_with_active_run_delayed():
    """Upload event: doc is deleting with an active run -> delayed, no RunRequest."""
    active_run = MagicMock()
    active_run.is_finished = False

    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}
    ])
    result = _run_sensor(
        fake_redis,
        pg_doc_status={"status": "deleting", "run_id": "run-del-active"},
        get_run_by_id=lambda _: active_run,
    )

    assert result == []
    assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 1


def test_sensor_upload_deleting_no_run_id_dispatches():
    """Upload event: doc is deleting but run_id is empty (orphaned status) -> dispatch immediately.

    Reproduces the production bug where a daemon restart left docs stuck in
    status=deleting with no run_id, causing upload events to loop in the delay queue.
    """
    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}
    ])
    result = _run_sensor(
        fake_redis,
        pg_doc_status={"status": "deleting", "run_id": ""},
    )

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"
    assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 0


def test_sensor_upload_deleting_zombie_run_dispatches():
    """Upload event: doc is deleting but the delete run has finished -> zombie recovered, dispatched."""
    dead_run = MagicMock()
    dead_run.is_finished = True

    fake_redis = _make_redis(put_events=[
        {"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False}
    ])
    calls = []
    result = _run_sensor(
        fake_redis,
        pg_doc_status={"status": "deleting", "run_id": "run-del-dead"},
        get_run_by_id=lambda _: dead_run,
        set_failed_calls=calls,
    )

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"
    assert calls[0][2] == "run-del-dead"


def test_sensor_delete_blocked_by_active_run_delayed():
    """Delete event: doc has an active run (running or deleting) -> delayed, no RunRequest."""
    active_run = MagicMock()
    active_run.is_finished = False

    for status in ("running", "deleting"):
        fake_redis = _make_redis(delete_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf"}])
        result = _run_sensor(
            fake_redis,
            pg_doc_status={"status": status, "run_id": "run-active"},
            get_run_by_id=lambda _: active_run,
        )

        assert result == [], f"Expected delay for status={status}"
        assert len(fake_redis._zsets.get("rag:delete:delay", {})) == 1, f"Expected delay queue entry for status={status}"


def test_sensor_delete_zombie_run_dispatches():
    """Delete event: doc is running/deleting but run has finished -> zombie recovered, delete dispatched."""
    dead_run = MagicMock()
    dead_run.is_finished = True

    fake_redis = _make_redis(delete_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf"}])
    calls = []
    result = _run_sensor(
        fake_redis,
        pg_doc_status={"status": "running", "run_id": "run-dead"},
        get_run_by_id=lambda _: dead_run,
        set_failed_calls=calls,
    )

    assert len(result) == 1
    assert result[0].job_name == "delete_job"
    assert calls[0][2] == "run-dead"


def test_sensor_delete_no_run_id_dispatches():
    """Delete event: doc is running/deleting but run_id is empty -> dispatch immediately."""
    for status in ("running", "deleting"):
        fake_redis = _make_redis(delete_events=[{"kb_id": "kb-test", "doc_source": "doc.pdf"}])
        result = _run_sensor(
            fake_redis,
            pg_doc_status={"status": status, "run_id": ""},
        )

        assert len(result) == 1, f"Expected dispatch for status={status}"
        assert result[0].job_name == "delete_job"


def test_sensor_drain_delay_queue():
    """Ready item in delay queue is moved to main queue and dispatched."""
    raw = json.dumps({"kb_id": "kb-test", "doc_source": "doc.pdf", "etag": "etag-001", "file_size": 0, "force": False})
    fake_redis = FakeRedis()
    fake_redis.zadd("rag:upload:delay", {raw: time.time() - 1})

    result = _run_sensor(fake_redis)

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"
    assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 0


def test_sensor_run_keys_unique():
    """Two events in one tick -> two different run_keys."""
    events = [
        {"kb_id": "kb-test", "doc_source": "a.pdf", "etag": "e1", "file_size": 0, "force": False},
        {"kb_id": "kb-test", "doc_source": "b.pdf", "etag": "e2", "file_size": 0, "force": False},
    ]
    result = _run_sensor(_make_redis(put_events=events))

    assert len(result) == 2
    assert result[0].run_key != result[1].run_key
