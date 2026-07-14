"""Unit tests for /api/kb — deletion and Dagster schedule cleanup."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rag_api.api.app import create_app

KB_ID = "kb-01"

_BASE_KB: dict[str, object] = {
    "kb_id": KB_ID,
    "kb_name": "KB 01",
    "description": None,
    "tags": [],
    "status": "active",
    "created_at": "2026-06-01T00:00:00+00:00",
    "updated_at": "2026-06-01T00:00:00+00:00",
}

_SCHEDULED_CONNECTOR = {
    "connector_id": "conn-web-01",
    "kb_id": KB_ID,
    "sync_schedule": "0 2 * * *",
    "sync_status": "idle",
}

_RUNNING_CONNECTOR = {
    "connector_id": "conn-web-02",
    "kb_id": KB_ID,
    "sync_schedule": None,
    "sync_status": "running",
}


@pytest.fixture
def client():
    with patch("rag_api.api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


class TestDeleteKB:

    def test_returns_404_for_unknown_kb(self, client):
        with patch("rag_api.infra.postgres.get_kb_meta", return_value=None):
            resp = client.delete(f"/api/kb/{KB_ID}")
        assert resp.status_code == 404

    def test_reloads_dagster_when_connector_had_schedule(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.update_kb_status"),
            patch("rag_api.infra.postgres.list_connectors", return_value=[_SCHEDULED_CONNECTOR]) as mock_list,
            patch("rag_api.infra.postgres.get_active_ingest_docs_for_kb", return_value=[]),
            patch("rag_api.infra.qdrant.drop_collection"),
            patch("rag_api.infra.s3.delete_kb_prefix", return_value=3),
            patch("rag_api.infra.postgres.delete_kb_meta") as mock_delete_meta,
            patch("rag_api.infra.dagster_utils.reload_code_location") as mock_reload,
        ):
            resp = client.delete(f"/api/kb/{KB_ID}")

        assert resp.status_code == 200
        mock_list.assert_called_once_with(kb_id=KB_ID)
        mock_delete_meta.assert_called_once_with(KB_ID)
        mock_reload.assert_called_once()

    def test_returns_409_when_connector_sync_running(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.list_connectors", return_value=[_RUNNING_CONNECTOR]),
            patch("rag_api.infra.postgres.update_kb_status") as mock_status,
            patch("rag_api.infra.postgres.delete_kb_meta") as mock_delete_meta,
        ):
            resp = client.delete(f"/api/kb/{KB_ID}")

        assert resp.status_code == 409
        mock_status.assert_not_called()
        mock_delete_meta.assert_not_called()

    def test_skips_dagster_reload_when_no_scheduled_connectors(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.update_kb_status"),
            patch("rag_api.infra.postgres.list_connectors", return_value=[]),
            patch("rag_api.infra.postgres.get_active_ingest_docs_for_kb", return_value=[]),
            patch("rag_api.infra.qdrant.drop_collection"),
            patch("rag_api.infra.s3.delete_kb_prefix", return_value=0),
            patch("rag_api.infra.postgres.delete_kb_meta"),
            patch("rag_api.infra.dagster_utils.reload_code_location") as mock_reload,
        ):
            resp = client.delete(f"/api/kb/{KB_ID}")

        assert resp.status_code == 200
        mock_reload.assert_not_called()

    def test_aborts_active_ingest_before_delete(self, client):
        active_doc = {"doc_id": "doc-active", "status": "pending", "run_id": ""}

        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.update_kb_status"),
            patch("rag_api.infra.postgres.list_connectors", return_value=[]),
            patch(
                "rag_api.infra.postgres.get_active_ingest_docs_for_kb",
                return_value=[active_doc],
            ),
            patch("rag_api.pipeline.utils.abort_ingest.abort_active_ingest") as mock_abort,
            patch("rag_api.infra.qdrant.drop_collection"),
            patch("rag_api.infra.s3.delete_kb_prefix", return_value=0),
            patch("rag_api.infra.postgres.delete_kb_meta"),
        ):
            resp = client.delete(f"/api/kb/{KB_ID}")

        assert resp.status_code == 200
        mock_abort.assert_called_once_with([active_doc])
