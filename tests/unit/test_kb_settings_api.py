"""Unit tests for /api/kb/{kb_id}/settings(/overrides) — docs/internal/design/kb-settings-override.md."""

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


@pytest.fixture
def client():
    with patch("rag_api.api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


class TestGetEffectiveSettings:
    def test_returns_404_for_unknown_kb(self, client):
        with patch("rag_api.infra.postgres.get_kb_meta", return_value=None):
            resp = client.get(f"/api/kb/{KB_ID}/settings")
        assert resp.status_code == 404

    def test_returns_only_ingestion_chunking_dedup_sections(self, client):
        """Must never leak provider/redis/postgres/qdrant credentials through this endpoint —
        see design doc §9.2 (security fix from review)."""
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.get_kb_settings_overrides", return_value={}),
        ):
            resp = client.get(f"/api/kb/{KB_ID}/settings")

        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"ingestion", "chunking", "dedup"}
        assert "provider" not in body
        assert "redis" not in body
        assert "postgres" not in body
        assert "qdrant" not in body

    def test_reflects_stored_override(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch(
                "rag_api.infra.postgres.get_kb_settings_overrides",
                return_value={"chunking.chunk_size": 512},
            ),
        ):
            resp = client.get(f"/api/kb/{KB_ID}/settings")

        assert resp.status_code == 200
        assert resp.json()["chunking"]["chunk_size"] == 512


class TestGetOverrides:
    def test_returns_404_for_unknown_kb(self, client):
        with patch("rag_api.infra.postgres.get_kb_meta", return_value=None):
            resp = client.get(f"/api/kb/{KB_ID}/settings/overrides")
        assert resp.status_code == 404

    def test_returns_empty_dict_when_no_overrides(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.get_kb_settings_overrides", return_value={}),
        ):
            resp = client.get(f"/api/kb/{KB_ID}/settings/overrides")

        assert resp.status_code == 200
        assert resp.json() == {"overrides": {}}


class TestPutOverrides:
    def test_returns_404_for_unknown_kb(self, client):
        with patch("rag_api.infra.postgres.get_kb_meta", return_value=None):
            resp = client.put(f"/api/kb/{KB_ID}/settings/overrides", json={"overrides": {}})
        assert resp.status_code == 404

    def test_replaces_overrides(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.replace_kb_settings_overrides") as mock_replace,
        ):
            resp = client.put(
                f"/api/kb/{KB_ID}/settings/overrides",
                json={"overrides": {"ingestion.max_file_size_mb": 50}},
            )

        assert resp.status_code == 200
        mock_replace.assert_called_once_with(KB_ID, {"ingestion.max_file_size_mb": 50})

    def test_rejects_key_outside_allowed_sections(self, client):
        """provider/redis/postgres/etc are not in ingestion./chunking./dedup. — must be
        rejected, not silently written (security fix from design review)."""
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.replace_kb_settings_overrides") as mock_replace,
        ):
            resp = client.put(
                f"/api/kb/{KB_ID}/settings/overrides",
                json={"overrides": {"provider.openai_api_key": "stolen"}},
            )

        assert resp.status_code == 422
        mock_replace.assert_not_called()

    def test_rejects_deny_listed_key(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.replace_kb_settings_overrides") as mock_replace,
        ):
            resp = client.put(
                f"/api/kb/{KB_ID}/settings/overrides",
                json={"overrides": {"ingestion.parser_plugins": ["evil:register"]}},
            )

        assert resp.status_code == 422
        mock_replace.assert_not_called()

    def test_rejects_unknown_field(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.replace_kb_settings_overrides") as mock_replace,
        ):
            resp = client.put(
                f"/api/kb/{KB_ID}/settings/overrides",
                json={"overrides": {"ingestion.does_not_exist": 1}},
            )

        assert resp.status_code == 422
        mock_replace.assert_not_called()


class TestPatchOverrides:
    def test_returns_404_for_unknown_kb(self, client):
        with patch("rag_api.infra.postgres.get_kb_meta", return_value=None):
            resp = client.patch(f"/api/kb/{KB_ID}/settings/overrides", json={"overrides": {}})
        assert resp.status_code == 404

    def test_upserts_non_null_values(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.upsert_kb_settings_override") as mock_upsert,
            patch("rag_api.infra.postgres.delete_kb_settings_override") as mock_delete,
            patch("rag_api.infra.postgres.get_kb_settings_overrides", return_value={"chunking.chunk_size": 512}),
        ):
            resp = client.patch(
                f"/api/kb/{KB_ID}/settings/overrides",
                json={"overrides": {"chunking.chunk_size": 512}},
            )

        assert resp.status_code == 200
        mock_upsert.assert_called_once_with(KB_ID, "chunking.chunk_size", 512)
        mock_delete.assert_not_called()

    def test_null_value_deletes_key(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.upsert_kb_settings_override") as mock_upsert,
            patch("rag_api.infra.postgres.delete_kb_settings_override") as mock_delete,
            patch("rag_api.infra.postgres.get_kb_settings_overrides", return_value={}),
        ):
            resp = client.patch(
                f"/api/kb/{KB_ID}/settings/overrides",
                json={"overrides": {"chunking.chunk_size": None}},
            )

        assert resp.status_code == 200
        mock_delete.assert_called_once_with(KB_ID, "chunking.chunk_size")
        mock_upsert.assert_not_called()

    def test_rejects_disallowed_key_before_any_write(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.upsert_kb_settings_override") as mock_upsert,
            patch("rag_api.infra.postgres.delete_kb_settings_override") as mock_delete,
        ):
            resp = client.patch(
                f"/api/kb/{KB_ID}/settings/overrides",
                json={"overrides": {"redis.host": "evil.example.com"}},
            )

        assert resp.status_code == 422
        mock_upsert.assert_not_called()
        mock_delete.assert_not_called()


class TestDeleteOverrides:
    def test_returns_404_for_unknown_kb(self, client):
        with patch("rag_api.infra.postgres.get_kb_meta", return_value=None):
            resp = client.delete(f"/api/kb/{KB_ID}/settings/overrides")
        assert resp.status_code == 404

    def test_clears_all_overrides(self, client):
        with (
            patch("rag_api.infra.postgres.get_kb_meta", return_value=_BASE_KB),
            patch("rag_api.infra.postgres.clear_kb_settings_overrides") as mock_clear,
        ):
            resp = client.delete(f"/api/kb/{KB_ID}/settings/overrides")

        assert resp.status_code == 200
        mock_clear.assert_called_once_with(KB_ID)
