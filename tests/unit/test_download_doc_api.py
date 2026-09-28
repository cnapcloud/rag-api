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


def _make_doc(storage_key: str, title: str | None = None, doc_type: str | None = None) -> dict:
    return {
        "doc_id": "11111111-0000-0000-0000-000000000001",
        "kb_id": "kb1",
        "storage_key": storage_key,
        "title": title,
        "doc_type": doc_type,
    }


def _mock_s3_response(body: bytes) -> dict[str, MagicMock]:
    resp = {"Body": MagicMock()}
    resp["Body"].iter_chunks.return_value = iter([body])
    return resp


class TestDownloadDocKoreanFilename:
    def test_non_ascii_filename_returns_200_with_rfc5987_header(self, client):
        storage_key = "kb1/경력기술서.pdf"
        doc = _make_doc(storage_key, title="경력기술서.pdf", doc_type="pdf")
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
        doc = _make_doc(storage_key, title="report.pdf", doc_type="pdf")
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
        doc = _make_doc(storage_key, title="경력기술서")
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


class TestBuildDownloadFilename:
    def test_title_without_extension_appends_doc_type(self):
        """title에 확장자가 없으면 doc_type을 확장자로 붙인다."""
        from rag_api.api.routers.docs import _build_download_filename

        assert _build_download_filename("How to Configure Widgets", "html", "doc-1") == (
            "How to Configure Widgets.html"
        )

    def test_title_with_extension_is_kept_as_is(self):
        """title이 이미 확장자로 끝나면 doc_type을 덧붙이지 않는다."""
        from rag_api.api.routers.docs import _build_download_filename

        assert _build_download_filename("README.md", "md", "doc-1") == "README.md"

    def test_illegal_filesystem_chars_are_replaced(self):
        """파일명에 쓸 수 없는 문자는 밑줄로 치환된다."""
        from rag_api.api.routers.docs import _build_download_filename

        assert _build_download_filename("Q3 Report: Revenue/Growth", "pdf", "doc-1") == (
            "Q3 Report_ Revenue_Growth.pdf"
        )

    def test_long_title_truncated_at_word_boundary_within_30_chars(self):
        """30자를 넘는 title은 단어 중간이 아니라 경계에서 잘린다."""
        from rag_api.api.routers.docs import _build_download_filename

        result = _build_download_filename(
            "How to Configure Widgets — Acme Docs", "html", "doc-1"
        )
        assert result == "How to Configure Widgets.html"

    def test_empty_title_falls_back_to_doc_id(self):
        """title이 비어있으면 doc_id를 파일명으로 사용한다."""
        from rag_api.api.routers.docs import _build_download_filename

        assert _build_download_filename("", "pdf", "doc-6") == "doc-6.pdf"

    def test_no_doc_type_keeps_title_without_extension(self):
        """title에도 확장자가 없고 doc_type도 없으면 확장자 없이 title 그대로 사용한다."""
        from rag_api.api.routers.docs import _build_download_filename

        assert _build_download_filename("Untitled", "", "doc-5") == "Untitled"
