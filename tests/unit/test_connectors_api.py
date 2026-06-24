"""Unit tests for /api/connectors — CRUD and sync endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app

CONNECTOR_ID = "conn-web-01"
KB_ID = "kb-01"

_BASE_CONNECTOR = {
    "connector_id": CONNECTOR_ID,
    "kb_id": KB_ID,
    "name": "Product Docs",
    "source_type": "web",
    "config": {"seed_urls": ["https://example.com/docs"], "depth": 2},
    "sync_schedule": "0 2 * * *",
    "schedule_enabled": True,
    "sync_status": "idle",
    "sync_started_at": None,
    "last_synced_at": None,
    "status": "active",
    "created_at": "2026-06-01T00:00:00+00:00",
    "updated_at": "2026-06-01T00:00:00+00:00",
}

_BASE_KB = {
    "kb_id": KB_ID,
    "kb_name": "KB 01",
    "description": None,
    "tags": [],
    "status": "active",
    "created_at": "2026-06-01T00:00:00+00:00",
    "updated_at": "2026-06-01T00:00:00+00:00",
}


@pytest.fixture
def client():
    with patch("api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


# ──────────────────────────────────────────────
# POST /api/connectors
# ──────────────────────────────────────────────

class TestCreateConnector:

    def test_returns_201_with_connector(self, client):
        with (
            patch("infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("infra.postgres.create_connector", return_value=_BASE_CONNECTOR),
        ):
            resp = client.post("/api/connectors", json={
                "connector_id": CONNECTOR_ID,
                "kb_id": KB_ID,
                "name": "Product Docs",
                "source_type": "web",
                "config": {"seed_urls": ["https://example.com/docs"], "depth": 2},
                "sync_schedule": "0 2 * * *",
                "schedule_enabled": True,
            })

        assert resp.status_code == 201
        body = resp.json()
        assert body["connector_id"] == CONNECTOR_ID
        assert body["source_type"] == "web"

    def test_web_connector_without_seed_urls_returns_422(self, client):
        resp = client.post("/api/connectors", json={
            "connector_id": CONNECTOR_ID,
            "kb_id": KB_ID,
            "name": "Bad Config",
            "source_type": "web",
            "config": {},
        })

        assert resp.status_code == 422
        assert "seed_urls" in resp.text

    def test_web_connector_with_empty_seed_urls_returns_422(self, client):
        resp = client.post("/api/connectors", json={
            "connector_id": CONNECTOR_ID,
            "kb_id": KB_ID,
            "name": "Bad Config",
            "source_type": "web",
            "config": {"seed_urls": []},
        })

        assert resp.status_code == 422

    def test_non_web_connector_without_seed_urls_is_accepted(self, client):
        with (
            patch("infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("infra.postgres.create_connector", return_value={
                **_BASE_CONNECTOR, "source_type": "confluence",
            }),
        ):
            resp = client.post("/api/connectors", json={
                "connector_id": CONNECTOR_ID,
                "kb_id": KB_ID,
                "name": "Confluence",
                "source_type": "confluence",
                "config": {"base_url": "https://company.atlassian.net", "space_key": "DEV"},
            })

        assert resp.status_code == 201

    def test_kb_not_found_returns_404(self, client):
        with patch("infra.postgres.get_kb_meta", return_value=None):
            resp = client.post("/api/connectors", json={
                "connector_id": CONNECTOR_ID,
                "kb_id": "missing-kb",
                "name": "X",
                "source_type": "web",
                "config": {"seed_urls": ["https://example.com"]},
            })

        assert resp.status_code == 404

    def test_duplicate_connector_returns_409(self, client):
        import psycopg.errors

        def raise_unique(**_kw):
            raise psycopg.errors.UniqueViolation()

        with (
            patch("infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("infra.postgres.create_connector", side_effect=raise_unique),
        ):
            resp = client.post("/api/connectors", json={
                "connector_id": CONNECTOR_ID,
                "kb_id": KB_ID,
                "name": "X",
                "source_type": "web",
                "config": {"seed_urls": ["https://example.com"]},
            })

        assert resp.status_code == 409


# ──────────────────────────────────────────────
# GET /api/connectors
# ──────────────────────────────────────────────

class TestListConnectors:

    def test_returns_items_list(self, client):
        with patch("infra.postgres.list_connectors", return_value=[_BASE_CONNECTOR]):
            resp = client.get("/api/connectors")

        assert resp.status_code == 200
        assert resp.json()["items"] == [_BASE_CONNECTOR]

    def test_passes_filter_params(self, client):
        captured = {}

        def fake_list(kb_id=None, source_type=None, status=None, **_kw):
            captured.update({"kb_id": kb_id, "source_type": source_type, "status": status})
            return []

        with patch("infra.postgres.list_connectors", side_effect=fake_list):
            client.get("/api/connectors?kb_id=kb-01&source_type=web&status=active")

        assert captured == {"kb_id": "kb-01", "source_type": "web", "status": "active"}

    def test_no_filter_passes_none(self, client):
        captured = {}

        def fake_list(kb_id=None, source_type=None, status=None, **_kw):
            captured.update({"kb_id": kb_id, "source_type": source_type, "status": status})
            return []

        with patch("infra.postgres.list_connectors", side_effect=fake_list):
            client.get("/api/connectors")

        assert captured == {"kb_id": None, "source_type": None, "status": None}


# ──────────────────────────────────────────────
# GET /api/connectors/{connector_id}
# ──────────────────────────────────────────────

class TestGetConnector:

    def test_returns_connector(self, client):
        with patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR):
            resp = client.get(f"/api/connectors/{CONNECTOR_ID}")

        assert resp.status_code == 200
        assert resp.json()["connector_id"] == CONNECTOR_ID

    def test_not_found_returns_404(self, client):
        with patch("infra.postgres.get_connector", return_value=None):
            resp = client.get("/api/connectors/nonexistent")

        assert resp.status_code == 404


# ──────────────────────────────────────────────
# PATCH /api/connectors/{connector_id}
# ──────────────────────────────────────────────

class TestPatchConnector:

    def test_updates_allowed_fields(self, client):
        updated = {**_BASE_CONNECTOR, "name": "New Name", "schedule_enabled": False}
        with (
            patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR),
            patch("infra.postgres.update_connector", return_value=updated),
        ):
            resp = client.patch(f"/api/connectors/{CONNECTOR_ID}", json={
                "name": "New Name",
                "schedule_enabled": False,
            })

        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"
        assert resp.json()["schedule_enabled"] is False

    def test_not_found_returns_404(self, client):
        with patch("infra.postgres.get_connector", return_value=None):
            resp = client.patch(f"/api/connectors/{CONNECTOR_ID}", json={"name": "X"})

        assert resp.status_code == 404

    def test_only_unset_fields_passed_to_update(self, client):
        captured = {}

        def fake_update(connector_id, fields):
            captured["fields"] = fields
            return _BASE_CONNECTOR

        with (
            patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR),
            patch("infra.postgres.update_connector", side_effect=fake_update),
        ):
            client.patch(f"/api/connectors/{CONNECTOR_ID}", json={"name": "Only Name"})

        assert set(captured["fields"].keys()) == {"name"}


# ──────────────────────────────────────────────
# DELETE /api/connectors/{connector_id}
# ──────────────────────────────────────────────

class TestDeleteConnector:

    def test_returns_202_and_triggers_cascade(self, client):
        with (
            patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR),
            patch("infra.postgres.set_connector_status") as mock_set_status,
            patch("infra.postgres.list_docs_by_connector", return_value=[]),
            patch("infra.postgres.delete_connector") as mock_delete,
        ):
            resp = client.delete(f"/api/connectors/{CONNECTOR_ID}")

        assert resp.status_code == 202
        assert resp.json()["status"] == "deleting"
        mock_set_status.assert_called_once_with(CONNECTOR_ID, "deleting")
        mock_delete.assert_called_once_with(CONNECTOR_ID)

    def test_not_found_returns_404(self, client):
        with patch("infra.postgres.get_connector", return_value=None):
            resp = client.delete(f"/api/connectors/{CONNECTOR_ID}")

        assert resp.status_code == 404

    def test_cascade_soft_deletes_docs(self, client):
        doc = {
            "doc_id": "aaaa-0001",
            "kb_id": KB_ID,
            "connector_id": CONNECTOR_ID,
            "storage_key": f"{KB_ID}/web/aaaa-0001.html",
            "status": "indexed",
        }
        soft_delete_calls = []

        with (
            patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR),
            patch("infra.postgres.set_connector_status"),
            patch("infra.postgres.list_docs_by_connector", return_value=[doc]),
            patch("infra.qdrant.delete_chunks_by_doc_id"),
            patch("infra.s3.delete_by_key"),
            patch("infra.postgres.soft_delete_doc", side_effect=lambda did: soft_delete_calls.append(did)),
            patch("infra.postgres.delete_connector"),
        ):
            resp = client.delete(f"/api/connectors/{CONNECTOR_ID}")

        assert resp.status_code == 202
        assert soft_delete_calls == ["aaaa-0001"]

    def test_cascade_s3_error_is_ignored(self, client):
        from botocore.exceptions import ClientError as S3ClientError

        doc = {
            "doc_id": "aaaa-0002",
            "kb_id": KB_ID,
            "connector_id": CONNECTOR_ID,
            "storage_key": f"{KB_ID}/web/aaaa-0002.html",
            "status": "indexed",
        }

        def raise_s3(_key):
            raise S3ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "DeleteObject")

        with (
            patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR),
            patch("infra.postgres.set_connector_status"),
            patch("infra.postgres.list_docs_by_connector", return_value=[doc]),
            patch("infra.qdrant.delete_chunks_by_doc_id"),
            patch("infra.s3.delete_by_key", side_effect=raise_s3),
            patch("infra.postgres.soft_delete_doc"),
            patch("infra.postgres.delete_connector"),
        ):
            resp = client.delete(f"/api/connectors/{CONNECTOR_ID}")

        assert resp.status_code == 202


# ──────────────────────────────────────────────
# POST /api/connectors/{connector_id}/sync
# ──────────────────────────────────────────────

class TestTriggerSync:

    def test_returns_202_and_sets_running(self, client):
        set_sync_calls = []

        with (
            patch("infra.postgres.get_connector", return_value={**_BASE_CONNECTOR}),
            patch("infra.postgres.set_connector_sync_status", side_effect=lambda *a, **kw: set_sync_calls.append(a)),
            patch("infra.postgres.set_connector_status"),
        ):
            resp = client.post(f"/api/connectors/{CONNECTOR_ID}/sync")

        assert resp.status_code == 202
        assert resp.json()["sync_status"] == "running"
        assert set_sync_calls[0] == (CONNECTOR_ID, "running")

    def test_not_found_returns_404(self, client):
        with patch("infra.postgres.get_connector", return_value=None):
            resp = client.post(f"/api/connectors/{CONNECTOR_ID}/sync")

        assert resp.status_code == 404

    def test_paused_connector_returns_409(self, client):
        with patch("infra.postgres.get_connector", return_value={**_BASE_CONNECTOR, "status": "paused"}):
            resp = client.post(f"/api/connectors/{CONNECTOR_ID}/sync")

        assert resp.status_code == 409
        assert "paused" in resp.json()["detail"]

    def test_running_within_timeout_returns_409(self, client):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        connector = {
            **_BASE_CONNECTOR,
            "sync_status": "running",
            "sync_started_at": recent,
        }
        with patch("infra.postgres.get_connector", return_value=connector):
            resp = client.post(f"/api/connectors/{CONNECTOR_ID}/sync")

        assert resp.status_code == 409
        assert "in progress" in resp.json()["detail"]

    def test_stale_lock_allows_retrigger(self, client):
        stale = (datetime.now(timezone.utc) - timedelta(minutes=35)).isoformat()
        connector = {
            **_BASE_CONNECTOR,
            "sync_status": "running",
            "sync_started_at": stale,
        }
        with (
            patch("infra.postgres.get_connector", return_value=connector),
            patch("infra.postgres.set_connector_sync_status"),
            patch("infra.postgres.set_connector_status"),
        ):
            resp = client.post(f"/api/connectors/{CONNECTOR_ID}/sync")

        assert resp.status_code == 202

    def test_background_task_marks_error_on_dispatch_failure(self, client):
        status_calls = []

        with (
            patch("infra.postgres.get_connector", return_value={**_BASE_CONNECTOR}),
            patch("infra.postgres.set_connector_sync_status"),
            patch("infra.postgres.set_connector_status", side_effect=lambda cid, s: status_calls.append(s)),
        ):
            client.post(f"/api/connectors/{CONNECTOR_ID}/sync")

        # _dispatch_sync raises ConfigError; _run_sync catches it and sets status=error
        assert "error" in status_calls


# ──────────────────────────────────────────────
# GET /api/connectors/{connector_id}/sync/status
# ──────────────────────────────────────────────

class TestGetSyncStatus:

    def test_returns_sync_state_and_doc_counts(self, client):
        counts = {"indexed": 10, "failed": 1, "total": 11}
        with (
            patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR),
            patch("infra.postgres.get_connector_doc_counts", return_value=counts),
        ):
            resp = client.get(f"/api/connectors/{CONNECTOR_ID}/sync/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["connector_id"] == CONNECTOR_ID
        assert body["sync_status"] == "idle"
        assert body["doc_counts"]["total"] == 11
        assert body["doc_counts"]["indexed"] == 10

    def test_not_found_returns_404(self, client):
        with patch("infra.postgres.get_connector", return_value=None):
            resp = client.get(f"/api/connectors/{CONNECTOR_ID}/sync/status")

        assert resp.status_code == 404


# ──────────────────────────────────────────────
# POST /api/connectors/{connector_id}/sync/reset
# ──────────────────────────────────────────────

class TestResetSyncStatus:

    def test_resets_running_to_idle(self, client):
        running = {**_BASE_CONNECTOR, "sync_status": "running"}
        with (
            patch("infra.postgres.get_connector", return_value=running),
            patch("infra.postgres.set_connector_sync_status") as mock_set,
        ):
            resp = client.post(f"/api/connectors/{CONNECTOR_ID}/sync/reset")

        assert resp.status_code == 200
        assert resp.json()["sync_status"] == "idle"
        mock_set.assert_called_once_with(CONNECTOR_ID, "idle")

    def test_resets_idle_connector_too(self, client):
        with (
            patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR),
            patch("infra.postgres.set_connector_sync_status") as mock_set,
        ):
            resp = client.post(f"/api/connectors/{CONNECTOR_ID}/sync/reset")

        assert resp.status_code == 200
        mock_set.assert_called_once_with(CONNECTOR_ID, "idle")

    def test_not_found_returns_404(self, client):
        with patch("infra.postgres.get_connector", return_value=None):
            resp = client.post(f"/api/connectors/{CONNECTOR_ID}/sync/reset")

        assert resp.status_code == 404


# ──────────────────────────────────────────────
# GET /api/connectors/{connector_id}/docs
# ──────────────────────────────────────────────

class TestListConnectorDocs:

    def test_returns_paginated_docs(self, client):
        doc = {
            "doc_id": "dddd-0001",
            "kb_id": KB_ID,
            "connector_id": CONNECTOR_ID,
            "source": "Getting Started",
            "status": "indexed",
        }
        with (
            patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR),
            patch("infra.postgres.list_docs_by_connector_paginated", return_value=([doc], 1)),
        ):
            resp = client.get(f"/api/connectors/{CONNECTOR_ID}/docs")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["doc_id"] == "dddd-0001"

    def test_not_found_returns_404(self, client):
        with patch("infra.postgres.get_connector", return_value=None):
            resp = client.get(f"/api/connectors/{CONNECTOR_ID}/docs")

        assert resp.status_code == 404

    def test_page_size_clamped_to_100(self, client):
        captured = {}

        def fake_paginated(connector_id, page, page_size, **_kw):
            captured["page_size"] = page_size
            return ([], 0)

        with (
            patch("infra.postgres.get_connector", return_value=_BASE_CONNECTOR),
            patch("infra.postgres.list_docs_by_connector_paginated", side_effect=fake_paginated),
        ):
            client.get(f"/api/connectors/{CONNECTOR_ID}/docs?page_size=999")

        assert captured["page_size"] == 100
