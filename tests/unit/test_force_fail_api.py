"""Unit tests for POST /api/kb/{kb_id}/docs/{doc_id}/fail."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from rag_api.api.app import create_app

KB_ID = "kb-01"
DOC_ID = "doc-abc-123"

_BASE_DOC = {
    "doc_id": DOC_ID,
    "kb_id": KB_ID,
    "status": "running",
    "run_id": "dagster-run-xyz",
}


@pytest.fixture
def client():
    with patch("rag_api.api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


def _doc(status: str, run_id: str = "") -> dict:
    return {**_BASE_DOC, "status": status, "run_id": run_id}


def _patch_terminate(side_effect=None):
    m = MagicMock(side_effect=side_effect)
    return patch("rag_api.infra.dagster_utils.terminate_dagster_run", m), m


class TestForceFail:
    def test_running_with_run_id_terminates_and_fails(self, client):
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("running", "run-1")),
            patch("rag_api.infra.dagster_utils.terminate_dagster_run") as mock_terminate,
            patch("rag_api.pipeline.queue.enqueue.dequeue_upload_events") as mock_dequeue,
            patch("rag_api.pipeline.utils.doc_state.set_failed") as mock_fail,
        ):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        mock_terminate.assert_called_once_with("run-1")
        mock_dequeue.assert_called_once_with(DOC_ID)
        mock_fail.assert_called_once()

    def test_deleting_with_run_id_terminates_and_fails(self, client):
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("deleting", "run-2")),
            patch("rag_api.infra.dagster_utils.terminate_dagster_run") as mock_terminate,
            patch("rag_api.pipeline.queue.enqueue.dequeue_upload_events") as mock_dequeue,
            patch("rag_api.pipeline.utils.doc_state.set_failed") as mock_fail,
        ):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 200
        mock_terminate.assert_called_once_with("run-2")
        mock_dequeue.assert_called_once_with(DOC_ID)
        mock_fail.assert_called_once()

    def test_pending_without_run_id_dequeues_and_fails(self, client):
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("pending")),
            patch("rag_api.infra.dagster_utils.terminate_dagster_run") as mock_terminate,
            patch("rag_api.pipeline.queue.enqueue.dequeue_upload_events") as mock_dequeue,
            patch("rag_api.pipeline.utils.doc_state.set_failed") as mock_fail,
        ):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 200
        mock_terminate.assert_not_called()
        mock_dequeue.assert_called_once_with(DOC_ID)
        mock_fail.assert_called_once()

    def test_pending_with_run_id_terminates_and_dequeues(self, client):
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("pending", "run-3")),
            patch("rag_api.infra.dagster_utils.terminate_dagster_run") as mock_terminate,
            patch("rag_api.pipeline.queue.enqueue.dequeue_upload_events") as mock_dequeue,
            patch("rag_api.pipeline.utils.doc_state.set_failed") as mock_fail,
        ):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 200
        mock_terminate.assert_called_once_with("run-3")
        mock_dequeue.assert_called_once_with(DOC_ID)
        mock_fail.assert_called_once()

    def test_uploading_without_run_id_fails_directly(self, client):
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("uploading")),
            patch("rag_api.infra.dagster_utils.terminate_dagster_run") as mock_terminate,
            patch("rag_api.pipeline.queue.enqueue.dequeue_upload_events") as mock_dequeue,
            patch("rag_api.pipeline.utils.doc_state.set_failed") as mock_fail,
        ):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 200
        mock_terminate.assert_not_called()
        mock_dequeue.assert_called_once_with(DOC_ID)
        mock_fail.assert_called_once()

    def test_custom_reason_stored_in_error(self, client):
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("running", "run-1")),
            patch("rag_api.infra.dagster_utils.terminate_dagster_run"),
            patch("rag_api.pipeline.queue.enqueue.dequeue_upload_events"),
            patch("rag_api.pipeline.utils.doc_state.set_failed") as mock_fail,
        ):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail?reason=stuck+in+prod")
        assert resp.status_code == 200
        mock_fail.assert_called_once()
        args = mock_fail.call_args
        assert "stuck in prod" in args[0][1]

    def test_indexed_returns_409(self, client):
        with patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("indexed")):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 409

    def test_failed_returns_409(self, client):
        with patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("failed")):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 409

    def test_doc_not_found_returns_404(self, client):
        with patch("rag_api.infra.postgres.get_doc_by_id", return_value=None):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 404

    def test_wrong_kb_returns_404(self, client):
        with patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("running", "run-1")):
            resp = client.post(f"/api/kb/other-kb/docs/{DOC_ID}/fail")
        assert resp.status_code == 404

    def test_terminate_failure_propagates_as_500(self, client):
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("running", "run-1")),
            patch(
                "rag_api.infra.dagster_utils.terminate_dagster_run",
                side_effect=RuntimeError("Dagster force-terminate failed"),
            ),
            patch("rag_api.pipeline.utils.doc_state.set_failed") as mock_fail,
        ):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 500
        mock_fail.assert_not_called()


    def test_queue_worker_mode_skips_terminate(self, client):
        fake_cfg = MagicMock()
        fake_cfg.queue_worker.enabled = True
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=_doc("running", "run-1")),
            patch("rag_api.config.settings.get_settings", return_value=fake_cfg),
            patch("rag_api.infra.dagster_utils.terminate_dagster_run"),
            patch("rag_api.pipeline.queue.enqueue.dequeue_upload_events") as mock_dequeue,
            patch("rag_api.pipeline.utils.doc_state.set_failed") as mock_fail,
        ):
            resp = client.post(f"/api/kb/{KB_ID}/docs/{DOC_ID}/fail")
        assert resp.status_code == 200
        mock_dequeue.assert_called_once_with(DOC_ID)
        mock_fail.assert_called_once()
