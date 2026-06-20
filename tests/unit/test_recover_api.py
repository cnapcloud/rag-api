"""Unit tests for POST /api/kb/{kb_id}/docs/{key}/recover — US-05."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.fixture
def client():
    with patch("api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


def _patch_redis_queue():
    """Return a fake Redis client that captures lpush calls."""
    queued = []

    class FakeRedis:
        def lpush(self, key, value):
            queued.append((key, value))

    return FakeRedis(), queued


class TestRecoverDocEndpoint:

    def test_running_doc_returns_202_and_requeues(self, client):
        """status=running doc -> 202, set_failed called, event pushed to upload queue."""
        fake_redis, queued = _patch_redis_queue()
        set_failed_calls = []

        def fake_set_failed(kb_id, key, error, run_id=""):
            set_failed_calls.append({"kb_id": kb_id, "key": key})

        with (
            patch("infra.postgres.get_doc_status", return_value={"status": "running", "run_id": "r1", "etag": "e1"}),
            patch("pipeline.ops.meta.set_failed", side_effect=fake_set_failed),
            patch("infra.redis.get_redis_client", return_value=fake_redis),
        ):
            resp = client.post("/api/kb/kb-test/docs/doc.pdf/recover")

        assert resp.status_code == 202
        body = resp.json()
        assert body["kb_id"] == "kb-test"
        assert body["doc_source"] == "doc.pdf"
        assert body["queued"] is True

        assert len(set_failed_calls) == 1
        assert set_failed_calls[0]["kb_id"] == "kb-test"

        assert len(queued) == 1
        key, raw = queued[0]
        assert key == "rag:upload:queue"
        event = json.loads(raw)
        assert event["kb_id"] == "kb-test"
        assert event["doc_source"] == "doc.pdf"
        assert event["force"] is True

    def test_indexed_doc_returns_409(self, client):
        """status=indexed doc -> 409 ConflictError."""
        with patch("infra.postgres.get_doc_status", return_value={"status": "indexed"}):
            resp = client.post("/api/kb/kb-test/docs/doc.pdf/recover")

        assert resp.status_code == 409

    def test_missing_doc_returns_404(self, client):
        """Non-existent doc -> 404 NotFoundError."""
        with patch("infra.postgres.get_doc_status", return_value=None):
            resp = client.post("/api/kb/kb-test/docs/missing.pdf/recover")

        assert resp.status_code == 404

    def test_failed_doc_returns_409(self, client):
        """status=failed doc -> 409 (not recoverable via this endpoint)."""
        with patch("infra.postgres.get_doc_status", return_value={"status": "failed", "error": "oops"}):
            resp = client.post("/api/kb/kb-test/docs/doc.pdf/recover")

        assert resp.status_code == 409
