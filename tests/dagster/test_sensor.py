"""event_queue_sensor unit tests."""

from __future__ import annotations

import json
import time
from contextlib import ExitStack
from unittest.mock import MagicMock, PropertyMock, patch

DOC_ID = "11111111-1111-1111-1111-111111111111"
DOC_ID_2 = "22222222-2222-2222-2222-222222222222"


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
    pg_doc_by_id=None,
    get_run_by_id=None,
    set_failed_calls=None,
):
    """Execute the sensor once and return RunRequest objects.

    pg_doc_by_id: value returned by infra.postgres.get_doc_by_id (None or dict).
    """
    from dagster import RunRequest, build_sensor_context
    from defs.sensors.event_queue_sensor import event_queue_sensor

    mock_settings = MagicMock()
    mock_settings.queue_worker.enabled = False

    ctx = build_sensor_context()
    with ExitStack() as stack:
        stack.enter_context(patch("infra.redis.get_redis_client", return_value=fake_redis))
        stack.enter_context(
            patch("defs.sensors.event_queue_sensor._get_settings", return_value=mock_settings)
        )
        stack.enter_context(patch("infra.postgres.get_doc_by_id", return_value=pg_doc_by_id))
        stack.enter_context(patch("infra.postgres.update_doc_fields"))
        stack.enter_context(patch("pipeline.ops.meta.update_doc_fields"))
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
                    side_effect=lambda doc_id, err, run_id="": set_failed_calls.append((doc_id, run_id)),
                )
            )
        return [r for r in event_queue_sensor(ctx) if isinstance(r, RunRequest)]


def test_upload_sensor_put_generates_ingest_run():
    """PUT event -> ingest_job RunRequest with doc_id in config and tags."""
    fake_redis = _make_redis(put_events=[{"doc_id": DOC_ID, "force": False}])
    doc = {"doc_id": DOC_ID, "kb_id": "kb-test", "status": "indexed", "run_id": ""}
    result = _run_sensor(fake_redis, pg_doc_by_id=doc)

    assert len(result) == 1
    req = result[0]
    assert req.job_name == "ingest_job"
    assert req.tags.get("doc_id") == DOC_ID
    assert req.tags.get("kb_id") == "kb-test"
    assert req.run_key
    cfg = req.run_config["ops"]["validate_op"]["config"]
    assert cfg["doc_id"] == DOC_ID
    assert cfg["force"] is False


def test_upload_sensor_delete_generates_delete_run():
    """DELETE event -> delete_job RunRequest with doc_id in tags."""
    fake_redis = _make_redis(delete_events=[{"doc_id": DOC_ID}])
    doc = {"doc_id": DOC_ID, "kb_id": "kb-test", "status": "indexed", "run_id": ""}
    result = _run_sensor(fake_redis, pg_doc_by_id=doc)

    assert len(result) == 1
    req = result[0]
    assert req.job_name == "delete_job"
    assert req.tags.get("doc_id") == DOC_ID
    assert req.tags.get("kb_id") == "kb-test"
    assert req.run_key


def test_upload_sensor_no_events():
    """Empty queues -> no RunRequests."""
    result = _run_sensor(_make_redis())
    assert result == []


def test_upload_sensor_batch_put():
    """Multiple PUT events -> all consumed in one sensor tick."""
    events = [
        {"doc_id": f"aaaaaaaa-0000-0000-0000-{i:012d}", "force": False}
        for i in range(5)
    ]
    result = _run_sensor(_make_redis(put_events=events))

    assert len(result) == 5
    assert all(r.job_name == "ingest_job" for r in result)


def test_upload_sensor_mixed_queues():
    """PUT and DELETE events consumed together in one tick."""
    fake_redis = _make_redis(
        put_events=[{"doc_id": DOC_ID, "force": False}],
        delete_events=[{"doc_id": DOC_ID_2}],
    )
    result = _run_sensor(fake_redis)

    assert len(result) == 2
    job_names = {r.job_name for r in result}
    assert "ingest_job" in job_names
    assert "delete_job" in job_names


def test_upload_sensor_force_flag_propagated():
    """force=True in PUT event -> run_config carries force=True."""
    fake_redis = _make_redis(put_events=[{"doc_id": DOC_ID, "force": True}])
    result = _run_sensor(fake_redis)

    assert len(result) == 1
    cfg = result[0].run_config["ops"]["validate_op"]["config"]
    assert cfg["force"] is True


def test_sensor_upload_skips_processing_doc():
    """Upload event: doc is actively running (Dagster run alive) -> delayed, no RunRequest."""
    active_run = MagicMock()
    active_run.is_finished = False

    fake_redis = _make_redis(put_events=[{"doc_id": DOC_ID, "force": False}])
    result = _run_sensor(
        fake_redis,
        pg_doc_by_id={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running", "run_id": "run-active"},
        get_run_by_id=lambda _: active_run,
    )

    assert result == []
    assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 1


def test_sensor_upload_zombie_run_dispatches():
    """Upload event: doc has status=running but Dagster run is finished -> zombie recovered, dispatched."""
    dead_run = MagicMock()
    dead_run.is_finished = True

    fake_redis = _make_redis(put_events=[{"doc_id": DOC_ID, "force": False}])
    calls = []
    result = _run_sensor(
        fake_redis,
        pg_doc_by_id={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running", "run_id": "run-dead"},
        get_run_by_id=lambda _: dead_run,
        set_failed_calls=calls,
    )

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"
    assert len(calls) == 1
    assert calls[0][1] == "run-dead"


def test_sensor_upload_run_not_found_dispatches():
    """Upload event: doc has run_id but Dagster returns None -> zombie recovered, dispatched."""
    fake_redis = _make_redis(put_events=[{"doc_id": DOC_ID, "force": False}])
    calls = []
    result = _run_sensor(
        fake_redis,
        pg_doc_by_id={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running", "run_id": "run-ghost"},
        get_run_by_id=lambda _: None,
        set_failed_calls=calls,
    )

    assert len(result) == 1
    assert len(calls) == 1
    assert calls[0][1] == "run-ghost"


def test_sensor_upload_dispatch_lock_remnant_dispatches():
    """Upload event: status=running with no run_id (dispatch lock remnant) -> dispatch immediately."""
    fake_redis = _make_redis(put_events=[{"doc_id": DOC_ID, "force": False}])
    result = _run_sensor(
        fake_redis,
        pg_doc_by_id={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running", "run_id": ""},
    )

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"


def test_sensor_upload_deleting_discarded():
    """Upload event: doc is deleting -> discarded (no delay queue, no RunRequest)."""
    for run_id in ("run-del-active", ""):
        fake_redis = _make_redis(put_events=[{"doc_id": DOC_ID, "force": False}])
        result = _run_sensor(
            fake_redis,
            pg_doc_by_id={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "deleting", "run_id": run_id},
        )

        assert result == [], f"Expected discard for run_id={run_id!r}"
        assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 0, f"Expected no delay queue entry for run_id={run_id!r}"


def test_sensor_delete_deleting_discarded():
    """Delete event: doc already deleting -> discarded (no delay queue, no RunRequest)."""
    fake_redis = _make_redis(delete_events=[{"doc_id": DOC_ID}])
    result = _run_sensor(
        fake_redis,
        pg_doc_by_id={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "deleting", "run_id": "run-del"},
    )

    assert result == []
    assert len(fake_redis._zsets.get("rag:delete:delay", {})) == 0


def test_sensor_delete_blocked_by_active_run_delayed():
    """Delete event: doc has an active run (running) -> delayed, no RunRequest."""
    active_run = MagicMock()
    active_run.is_finished = False

    fake_redis = _make_redis(delete_events=[{"doc_id": DOC_ID}])
    result = _run_sensor(
        fake_redis,
        pg_doc_by_id={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running", "run_id": "run-active"},
        get_run_by_id=lambda _: active_run,
    )

    assert result == []
    assert len(fake_redis._zsets.get("rag:delete:delay", {})) == 1


def test_sensor_delete_zombie_run_dispatches():
    """Delete event: doc is running/deleting but run has finished -> zombie recovered, delete dispatched."""
    dead_run = MagicMock()
    dead_run.is_finished = True

    fake_redis = _make_redis(delete_events=[{"doc_id": DOC_ID}])
    calls = []
    result = _run_sensor(
        fake_redis,
        pg_doc_by_id={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running", "run_id": "run-dead"},
        get_run_by_id=lambda _: dead_run,
        set_failed_calls=calls,
    )

    assert len(result) == 1
    assert result[0].job_name == "delete_job"
    assert calls[0][1] == "run-dead"


def test_sensor_delete_no_run_id_dispatches():
    """Delete event: doc is running but run_id is empty -> dispatch immediately."""
    fake_redis = _make_redis(delete_events=[{"doc_id": DOC_ID}])
    result = _run_sensor(
        fake_redis,
        pg_doc_by_id={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running", "run_id": ""},
    )

    assert len(result) == 1
    assert result[0].job_name == "delete_job"


def test_sensor_drain_delay_queue():
    """Ready item in delay queue is moved to main queue and dispatched."""
    raw = json.dumps({"doc_id": DOC_ID, "force": False})
    fake_redis = FakeRedis()
    fake_redis.zadd("rag:upload:delay", {raw: time.time() - 1})

    result = _run_sensor(fake_redis)

    assert len(result) == 1
    assert result[0].job_name == "ingest_job"
    assert len(fake_redis._zsets.get("rag:upload:delay", {})) == 0


def test_drain_delay_queue_sets_pending_when_not_running():
    """_drain_delay_queue: doc not running -> update_doc_fields called with status=pending."""
    from defs.sensors.event_queue_sensor import _drain_delay_queue

    raw = json.dumps({"doc_id": DOC_ID})
    fake_redis = FakeRedis()
    fake_redis.zadd("rag:upload:delay", {raw: time.time() - 1})

    update_calls = []

    with (
        patch("infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "status": "indexed"}),
        patch(
            "infra.postgres.update_doc_fields",
            side_effect=lambda doc_id, fields: update_calls.append((doc_id, fields)),
        ),
    ):
        _drain_delay_queue(fake_redis, "rag:upload:delay", "rag:upload:queue")

    assert len(update_calls) == 1
    assert update_calls[0][0] == DOC_ID
    assert update_calls[0][1].get("status") == "pending"
    assert fake_redis._lists.get("rag:upload:queue") == [raw]


def test_drain_delay_queue_skips_pending_when_still_running():
    """_drain_delay_queue: doc still running -> update_doc_fields NOT called, lpush still happens."""
    from defs.sensors.event_queue_sensor import _drain_delay_queue

    raw = json.dumps({"doc_id": DOC_ID})
    fake_redis = FakeRedis()
    fake_redis.zadd("rag:upload:delay", {raw: time.time() - 1})

    update_calls = []

    with (
        patch("infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "status": "running", "run_id": "r1"}),
        patch(
            "infra.postgres.update_doc_fields",
            side_effect=lambda doc_id, fields: update_calls.append((doc_id, fields)),
        ),
    ):
        _drain_delay_queue(fake_redis, "rag:upload:delay", "rag:upload:queue")

    assert len(update_calls) == 0
    assert fake_redis._lists.get("rag:upload:queue") == [raw]


def test_sensor_run_keys_unique():
    """Two events in one tick -> two different run_keys."""
    events = [
        {"doc_id": DOC_ID, "force": False},
        {"doc_id": DOC_ID_2, "force": False},
    ]
    result = _run_sensor(_make_redis(put_events=events))

    assert len(result) == 2
    assert result[0].run_key != result[1].run_key
