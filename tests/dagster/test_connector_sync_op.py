"""Unit tests for defs/ops/connector_sync_op.py — scheduled connector sync (R-12)."""

from __future__ import annotations

from unittest.mock import patch

from dagster import build_op_context

from rag_api.defs.ops.connector_sync_op import connector_sync_op

CONNECTOR_ID = "conn-web-01"

_BASE_CONNECTOR = {
    "connector_id": CONNECTOR_ID,
    "kb_id": "kb-01",
    "name": "Product Docs",
    "source_type": "web",
    "status": "error",
    "sync_status": "idle",
    "sync_started_at": None,
    "last_error": "old failure",
}


def _run(connector: dict, dispatch_side_effect=None):
    status_calls = []
    ctx = build_op_context(op_config={"connector_id": CONNECTOR_ID})
    with (
        patch("rag_api.infra.postgres.get_connector", return_value=connector),
        patch("rag_api.api.routers.connectors._dispatch_sync", side_effect=dispatch_side_effect),
        patch("rag_api.infra.postgres.set_connector_sync_status"),
        patch(
            "rag_api.infra.postgres.set_connector_status",
            side_effect=lambda cid, s, error=None: status_calls.append((s, error)),
        ),
    ):
        try:
            connector_sync_op(ctx)
        except Exception:
            pass
    return status_calls


def test_success_sets_status_active():
    status_calls = _run({**_BASE_CONNECTOR})
    assert status_calls == [("active", None)]


def test_dispatch_failure_sets_status_error_with_message():
    status_calls = _run(
        {**_BASE_CONNECTOR, "status": "active"},
        dispatch_side_effect=RuntimeError("boom"),
    )
    assert len(status_calls) == 1
    status, error = status_calls[0]
    assert status == "error"
    assert error == "boom"
