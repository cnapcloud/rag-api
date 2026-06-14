"""validate_op zombie recovery tests — US-05."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _fake_redis(doc_status: dict | None = None):
    """Return a FakeRedis and the underlying hash store."""
    hashes: dict = {}
    if doc_status is not None:
        hashes["doc:kb-test:doc.pdf"] = {k: str(v) for k, v in doc_status.items()}

    class FakeRedis:
        def hset(self, key, mapping=None, **kw):
            hashes.setdefault(key, {}).update({k: str(v) for k, v in (mapping or {}).items()})

        def hgetall(self, key):
            return dict(hashes.get(key, {}))

        def sadd(self, key, *values):
            pass

    return FakeRedis(), hashes


def _run_validate_op(dagster_run, doc_status, validate_return=True):
    """Invoke validate_op via build_op_context and return collected outputs."""
    from dagster import build_op_context

    fake_redis, hashes = _fake_redis(doc_status)

    set_failed_calls: list[dict] = []

    def fake_set_failed(kb_id, key, error, run_id=""):
        set_failed_calls.append({"kb_id": kb_id, "key": key, "error": error, "run_id": run_id})
        hashes.setdefault("doc:kb-test:doc.pdf", {})["status"] = "failed"

    ctx = build_op_context()
    with (
        patch.object(ctx.instance, "get_run_by_id", return_value=dagster_run),
        patch("infra.redis.get_redis_client", return_value=fake_redis),
        patch("pipeline.ops.validate.validate", return_value=validate_return),
        patch("pipeline.ops.meta.set_failed", side_effect=fake_set_failed),
    ):
        from dagster_pipeline.ops.ingest_ops import IngestConfig, validate_op

        cfg = IngestConfig(kb_id="kb-test", object_key="doc.pdf", etag="e1", file_size=0)
        outputs = list(validate_op(ctx, cfg))

    return outputs, set_failed_calls


class TestValidateOpZombieRecovery:

    def test_finished_run_id_triggers_recovery(self):
        """status=running + finished run → set_failed called, new processing proceeds."""
        finished_run = MagicMock()
        finished_run.is_finished = True

        outputs, set_failed_calls = _run_validate_op(
            dagster_run=finished_run,
            doc_status={"status": "running", "run_id": "run-old", "etag": "e0"},
        )

        assert len(set_failed_calls) == 1
        assert "run-old" in set_failed_calls[0]["error"]
        assert set_failed_calls[0]["run_id"] == "run-old"
        assert len(outputs) == 1

    def test_active_run_id_blocks_recovery(self):
        """status=running + active run → set_failed NOT called."""
        active_run = MagicMock()
        active_run.is_finished = False

        outputs, set_failed_calls = _run_validate_op(
            dagster_run=active_run,
            doc_status={"status": "running", "run_id": "run-active", "etag": "e0"},
        )

        assert len(set_failed_calls) == 0
        assert len(outputs) == 1

    def test_missing_run_id_triggers_recovery(self):
        """status=running + no run_id → set_failed called unconditionally."""
        outputs, set_failed_calls = _run_validate_op(
            dagster_run=None,
            doc_status={"status": "running", "etag": "e0"},
        )

        assert len(set_failed_calls) == 1
        assert "no run_id" in set_failed_calls[0]["error"]
        assert len(outputs) == 1

    def test_indexed_status_skips_recovery(self):
        """status=indexed → zombie detection not entered, set_failed not called."""
        outputs, set_failed_calls = _run_validate_op(
            dagster_run=None,
            doc_status={"status": "indexed", "run_id": "run-old", "etag": "e1"},
        )

        assert len(set_failed_calls) == 0
        assert len(outputs) == 1

    def test_run_not_found_triggers_recovery(self):
        """status=running + run_id present but Dagster returns None → set_failed called."""
        outputs, set_failed_calls = _run_validate_op(
            dagster_run=None,
            doc_status={"status": "running", "run_id": "run-ghost", "etag": "e0"},
        )

        assert len(set_failed_calls) == 1
        assert "run-ghost" in set_failed_calls[0]["error"]
        assert set_failed_calls[0]["run_id"] == "run-ghost"
        assert len(outputs) == 1
