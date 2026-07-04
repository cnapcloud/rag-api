"""Unit tests for POST /api/kb/{kb_id}/docs/{doc_id}/recover."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rag_api.api.app import create_app

DOC_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client():
    with patch("rag_api.api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


def _patch_redis_queue():
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

        def fake_set_failed(doc_id, error, run_id=""):
            set_failed_calls.append({"doc_id": doc_id})

        with (
            # get_doc_by_id called twice: once in recover_doc, once inside enqueue_upload_event
            patch("rag_api.infra.postgres.get_doc_by_id", side_effect=[
                {"doc_id": DOC_ID, "kb_id": "kb-test", "status": "running", "run_id": "r1"},
                {"doc_id": DOC_ID, "kb_id": "kb-test", "status": "failed"},
            ]),
            patch("rag_api.infra.postgres.update_doc_fields"),
            patch("rag_api.pipeline.ops.meta.set_failed", side_effect=fake_set_failed),
            patch("rag_api.infra.redis.get_redis_client", return_value=fake_redis),
        ):
            resp = client.post(f"/api/kb/kb-test/docs/{DOC_ID}/recover")

        assert resp.status_code == 202
        body = resp.json()
        assert body["kb_id"] == "kb-test"
        assert body["doc_id"] == DOC_ID
        assert body["queued"] is True

        assert len(set_failed_calls) == 1
        assert set_failed_calls[0]["doc_id"] == DOC_ID

        assert len(queued) == 1
        key, raw = queued[0]
        assert key == "rag:upload:queue"
        event = json.loads(raw)
        assert event["doc_id"] == DOC_ID
        assert event["force"] is True

    def test_indexed_doc_returns_409(self, client):
        """status=indexed doc -> 409 ConflictError."""
        with patch("rag_api.infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "indexed"}):
            resp = client.post(f"/api/kb/kb-test/docs/{DOC_ID}/recover")

        assert resp.status_code == 409

    def test_missing_doc_returns_404(self, client):
        """Non-existent doc -> 404 NotFoundError."""
        with patch("rag_api.infra.postgres.get_doc_by_id", return_value=None):
            resp = client.post(f"/api/kb/kb-test/docs/{DOC_ID}/recover")

        assert resp.status_code == 404

    def test_kb_mismatch_returns_404(self, client):
        """Doc belongs to different KB -> 404."""
        with patch("rag_api.infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "kb_id": "other-kb", "status": "running"}):
            resp = client.post(f"/api/kb/kb-test/docs/{DOC_ID}/recover")

        assert resp.status_code == 404

    def test_failed_doc_returns_409(self, client):
        """status=failed doc -> 409 (not recoverable via this endpoint)."""
        with patch("rag_api.infra.postgres.get_doc_by_id", return_value={"doc_id": DOC_ID, "kb_id": "kb-test", "status": "failed", "last_error": "oops"}):
            resp = client.post(f"/api/kb/kb-test/docs/{DOC_ID}/recover")

        assert resp.status_code == 409
