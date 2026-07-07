"""Unit tests for GET /api/kb/{kb_id}/docs/{doc_id}/download."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from rag_api.api.app import create_app


@pytest.fixture
def client():
    with patch("rag_api.api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


def _make_doc(storage_key: str) -> dict:
    return {
        "doc_id": "11111111-0000-0000-0000-000000000001",
        "kb_id": "kb1",
        "storage_key": storage_key,
    }


def _mock_s3_response(body: bytes) -> MagicMock:
    resp = {"Body": MagicMock()}
    resp["Body"].iter_chunks.return_value = iter([body])
    return resp


class TestDownloadDocKoreanFilename:
    def test_non_ascii_filename_returns_200_with_rfc5987_header(self, client):
        storage_key = "kb1/경력기술서.pdf"
        doc = _make_doc(storage_key)
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=doc),
            patch("rag_api.infra.s3.get_s3_client") as mock_get_client,
        ):
            mock_get_client.return_value.get_object.return_value = _mock_s3_response(b"content")
            resp = client.get("/api/kb/kb1/docs/11111111-0000-0000-0000-000000000001/download")

        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        assert "filename=\".pdf\"" in disposition
        assert f"filename*=UTF-8''{quote('경력기술서.pdf')}" in disposition

    def test_ascii_filename_unaffected(self, client):
        storage_key = "kb1/report.pdf"
        doc = _make_doc(storage_key)
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=doc),
            patch("rag_api.infra.s3.get_s3_client") as mock_get_client,
        ):
            mock_get_client.return_value.get_object.return_value = _mock_s3_response(b"content")
            resp = client.get("/api/kb/kb1/docs/11111111-0000-0000-0000-000000000001/download")

        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        assert disposition == "attachment; filename=\"report.pdf\"; filename*=UTF-8''report.pdf"

    def test_filename_with_no_ascii_chars_falls_back_to_download(self, client):
        storage_key = "kb1/경력기술서"
        doc = _make_doc(storage_key)
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=doc),
            patch("rag_api.infra.s3.get_s3_client") as mock_get_client,
        ):
            mock_get_client.return_value.get_object.return_value = _mock_s3_response(b"content")
            resp = client.get("/api/kb/kb1/docs/11111111-0000-0000-0000-000000000001/download")

        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"]
        assert "filename=\"download\"" in disposition

    def test_doc_not_found_returns_404(self, client):
        with patch("rag_api.infra.postgres.get_doc_by_id", return_value=None):
            resp = client.get("/api/kb/kb1/docs/does-not-exist/download")

        assert resp.status_code == 404
