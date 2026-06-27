"""Unit tests for ConfluenceConnector (R-10)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

KB_ID = "kb-01"
CONNECTOR_ID = "conn-cf-01"
SPACE_KEY = "DEV"
BASE_URL_CLOUD = "https://company.atlassian.net"
BASE_URL_SERVER = "https://confluence.company.com"

_PAGE_ID = "123456"
_PAGE_DOC_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_ATT_ID = "789012"
_ATT_DOC_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"

_PAGE_URI = f"confluence://{SPACE_KEY.lower()}/{_PAGE_ID}"
_ATT_URI = f"confluence://{SPACE_KEY.lower()}/attachments/{_ATT_ID}"

_HTML_BODY = "<p>Hello World content for testing.</p>"

_PAGE = {
    "id": _PAGE_ID,
    "title": "My Page",
    "version": {"number": 3},
    "metadata": {"labels": {"results": []}},
    "body": {"view": {"value": _HTML_BODY}},
}

_ATTACHMENT = {
    "id": _ATT_ID,
    "title": "report.pdf",
    "version": {"number": 2},
    "metadata": {"mediaType": "application/pdf"},
    "extensions": {"fileSize": 1024 * 1024},  # 1 MB
    "_links": {"download": f"/download/attachments/{_PAGE_ID}/report.pdf"},
}

_BASE_PAGE_DOC = {
    "doc_id": _PAGE_DOC_ID,
    "kb_id": KB_ID,
    "title": "My Page",
    "source_type": "confluence",
    "source": _PAGE_URI,
    "status": "indexed",
    "content_version": "3",
    "storage_key": f"{KB_ID}/confluence/{_PAGE_DOC_ID}.html",
    "connector_id": CONNECTOR_ID,
    "doc_type": "html",
}

_BASE_ATT_DOC = {
    "doc_id": _ATT_DOC_ID,
    "kb_id": KB_ID,
    "title": "report.pdf",
    "source_type": "confluence",
    "source": _ATT_URI,
    "status": "indexed",
    "content_version": "2",
    "storage_key": f"{KB_ID}/confluence/{_ATT_DOC_ID}.pdf",
    "connector_id": CONNECTOR_ID,
    "doc_type": "pdf",
}


def _make_client() -> MagicMock:
    client = MagicMock(spec=httpx.Client)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


def _make_confluence_connector(base_url: str = BASE_URL_CLOUD, extra: dict | None = None):
    from connectors.confluence import ConfluenceConnector

    config = {"base_url": base_url, "space_key": SPACE_KEY, "request_delay_ms": 0}
    config.update(extra or {})
    return ConfluenceConnector(config)


# ──────────────────────────────────────────────
# Config validation
# ──────────────────────────────────────────────

class TestInit:

    def test_missing_base_url_raises(self):
        from exceptions import ConfigError
        from connectors.confluence import ConfluenceConnector

        with pytest.raises(ConfigError, match="base_url"):
            ConfluenceConnector({"space_key": "DEV"})

    def test_missing_space_key_raises(self):
        from exceptions import ConfigError
        from connectors.confluence import ConfluenceConnector

        with pytest.raises(ConfigError, match="space_key"):
            ConfluenceConnector({"base_url": BASE_URL_CLOUD})

    def test_cloud_api_base(self):
        c = _make_confluence_connector(BASE_URL_CLOUD)
        assert c._api_base == f"{BASE_URL_CLOUD}/wiki/rest/api"

    def test_server_api_base(self):
        c = _make_confluence_connector(BASE_URL_SERVER)
        assert c._api_base == f"{BASE_URL_SERVER}/rest/api"

    def test_default_max_attachment_mb_is_10(self):
        c = _make_confluence_connector()
        assert c.max_attachment_bytes == 10 * 1024 * 1024

    def test_custom_max_attachment_mb(self):
        c = _make_confluence_connector(extra={"max_attachment_mb": 50})
        assert c.max_attachment_bytes == 50 * 1024 * 1024

    def test_basic_auth_from_email_colon_token(self):
        import base64

        c = _make_confluence_connector(extra={"auth_token_secret": "user@example.com:mytoken"})

        expected = "Basic " + base64.b64encode(b"user@example.com:mytoken").decode()
        assert c._auth_header == expected

    def test_bearer_auth_from_pat(self):
        c = _make_confluence_connector(extra={"auth_token_secret": "secret-pat-value"})

        assert c._auth_header == "Bearer secret-pat-value"

    def test_no_auth_when_no_secret(self):
        c = _make_confluence_connector()
        assert c._auth_header is None


# ──────────────────────────────────────────────
# _make_download_url
# ──────────────────────────────────────────────

class TestMakeDownloadUrl:

    def test_cloud_relative_url_prepends_wiki(self):
        c = _make_confluence_connector(BASE_URL_CLOUD)
        result = c._make_download_url("/download/attachments/123/file.pdf")
        assert result == f"{BASE_URL_CLOUD}/wiki/download/attachments/123/file.pdf"

    def test_server_relative_url_prepends_base(self):
        c = _make_confluence_connector(BASE_URL_SERVER)
        result = c._make_download_url("/download/attachments/123/file.pdf")
        assert result == f"{BASE_URL_SERVER}/download/attachments/123/file.pdf"

    def test_absolute_url_returned_as_is(self):
        c = _make_confluence_connector()
        url = "https://other.atlassian.net/wiki/download/attachments/123/file.pdf"
        assert c._make_download_url(url) == url


# ──────────────────────────────────────────────
# _has_excluded_label
# ──────────────────────────────────────────────

class TestHasExcludedLabel:

    def test_page_with_excluded_label_returns_true(self):
        c = _make_confluence_connector(extra={"exclude_labels": ["draft", "archived"]})
        page = {**_PAGE, "metadata": {"labels": {"results": [{"name": "draft"}]}}}
        assert c._has_excluded_label(page) is True

    def test_label_check_is_case_insensitive(self):
        c = _make_confluence_connector(extra={"exclude_labels": ["draft"]})
        page = {**_PAGE, "metadata": {"labels": {"results": [{"name": "DRAFT"}]}}}
        assert c._has_excluded_label(page) is True

    def test_page_without_excluded_label_returns_false(self):
        c = _make_confluence_connector(extra={"exclude_labels": ["draft"]})
        page = {**_PAGE, "metadata": {"labels": {"results": [{"name": "approved"}]}}}
        assert c._has_excluded_label(page) is False

    def test_no_exclude_labels_configured_returns_false(self):
        c = _make_confluence_connector()
        page = {**_PAGE, "metadata": {"labels": {"results": [{"name": "anything"}]}}}
        assert c._has_excluded_label(page) is False


# ──────────────────────────────────────────────
# _process_page
# ──────────────────────────────────────────────

class TestProcessPage:

    def test_new_page_creates_row_stages_and_enqueues(self):
        c = _make_confluence_connector()
        new_doc = {**_BASE_PAGE_DOC, "status": "fetching"}
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc) as mock_create,
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            c._process_page(client, KB_ID, CONNECTOR_ID, _PAGE)

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["source_type"] == "confluence"
        assert kwargs["doc_type"] == "html"
        assert kwargs["status"] == "fetching"
        assert kwargs["title"] == "My Page"

        mock_upload.assert_called_once()
        assert mock_upload.call_args.args[2] == _HTML_BODY.encode()
        assert mock_upload.call_args.kwargs["content_type"] == "text/html"

        pending_call = next(
            c for c in mock_update.call_args_list if c.args[1].get("status") == "pending"
        )
        assert pending_call.args[1]["storage_key"] == f"{KB_ID}/confluence/{_PAGE_DOC_ID}.html"
        assert pending_call.args[1]["content_version"] == "3"

        mock_enqueue.assert_called_once_with(_PAGE_DOC_ID, force=False)

    def test_unchanged_version_skips_staging_but_processes_attachments(self):
        c = _make_confluence_connector()
        existing_doc = {**_BASE_PAGE_DOC, "content_version": "3"}
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source", return_value=existing_doc),
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch.object(c, "_process_page_attachments") as mock_atts,
        ):
            c._process_page(client, KB_ID, CONNECTOR_ID, _PAGE)

        mock_upload.assert_not_called()
        mock_enqueue.assert_not_called()
        mock_atts.assert_called_once_with(client, KB_ID, CONNECTOR_ID, _PAGE_ID)

    def test_changed_version_restages_and_reenqueues(self):
        c = _make_confluence_connector()
        existing_doc = {**_BASE_PAGE_DOC, "content_version": "2"}
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source", return_value=existing_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object"),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch.object(c, "_process_page_attachments"),
        ):
            c._process_page(client, KB_ID, CONNECTOR_ID, _PAGE)

        statuses = [call.args[1].get("status") for call in mock_update.call_args_list if call.args[1].get("status")]
        assert "fetching" in statuses
        assert "pending" in statuses
        mock_enqueue.assert_called_once()

    def test_deleted_doc_is_refetched(self):
        c = _make_confluence_connector()
        deleted_doc = {**_BASE_PAGE_DOC, "status": "deleted", "content_version": "3"}
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source", return_value=deleted_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object"),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch.object(c, "_process_page_attachments"),
        ):
            c._process_page(client, KB_ID, CONNECTOR_ID, _PAGE)

        statuses = [call.args[1].get("status") for call in mock_update.call_args_list if call.args[1].get("status")]
        assert "fetching" in statuses
        mock_enqueue.assert_called_once()

    def test_excluded_label_skips_page_and_attachments(self):
        c = _make_confluence_connector(extra={"exclude_labels": ["draft"]})
        page = {**_PAGE, "metadata": {"labels": {"results": [{"name": "draft"}]}}}
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source") as mock_get,
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            c._process_page(client, KB_ID, CONNECTOR_ID, page)

        mock_get.assert_not_called()
        mock_upload.assert_not_called()
        mock_enqueue.assert_not_called()

    def test_s3_failure_sets_failed_and_still_processes_attachments(self):
        c = _make_confluence_connector()
        new_doc = {**_BASE_PAGE_DOC, "status": "fetching"}
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object", side_effect=Exception("S3 down")),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch.object(c, "_process_page_attachments") as mock_atts,
        ):
            c._process_page(client, KB_ID, CONNECTOR_ID, _PAGE)

        statuses = [call.args[1].get("status") for call in mock_update.call_args_list if call.args[1].get("status")]
        assert "failed" in statuses
        mock_enqueue.assert_not_called()
        mock_atts.assert_called_once()


# ──────────────────────────────────────────────
# _process_attachment
# ──────────────────────────────────────────────

class TestProcessAttachment:

    def _make_download_response(self, content: bytes = b"%PDF-1.4 test") -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.content = content
        resp.raise_for_status = MagicMock()
        return resp

    def test_new_attachment_stages_and_enqueues(self):
        c = _make_confluence_connector()
        new_doc = {**_BASE_ATT_DOC, "status": "fetching"}
        client = _make_client()
        client.get = MagicMock(return_value=self._make_download_response())

        with (
            patch("infra.postgres.get_doc_by_source", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc) as mock_create,
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            c._process_attachment(client, KB_ID, CONNECTOR_ID, _ATTACHMENT)

        mock_create.assert_called_once()
        kwargs = mock_create.call_args.kwargs
        assert kwargs["doc_type"] == "pdf"
        assert kwargs["title"] == "report.pdf"
        assert kwargs["source_type"] == "confluence"

        mock_upload.assert_called_once()
        pending_call = next(
            call for call in mock_update.call_args_list if call.args[1].get("status") == "pending"
        )
        assert pending_call.args[1]["storage_key"] == f"{KB_ID}/confluence/{_ATT_DOC_ID}.pdf"
        assert pending_call.args[1]["content_version"] == "2"
        mock_enqueue.assert_called_once_with(_ATT_DOC_ID, force=False)

    def test_unsupported_extension_skips(self):
        c = _make_confluence_connector()
        att = {**_ATTACHMENT, "title": "image.png"}
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source") as mock_get,
            patch("infra.s3.upload_object") as mock_upload,
        ):
            c._process_attachment(client, KB_ID, CONNECTOR_ID, att)

        mock_get.assert_not_called()
        mock_upload.assert_not_called()

    def test_too_large_skips(self):
        c = _make_confluence_connector(extra={"max_attachment_mb": 5})
        att = {**_ATTACHMENT, "extensions": {"fileSize": 6 * 1024 * 1024}}
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source") as mock_get,
            patch("infra.s3.upload_object") as mock_upload,
        ):
            c._process_attachment(client, KB_ID, CONNECTOR_ID, att)

        mock_get.assert_not_called()
        mock_upload.assert_not_called()

    def test_within_size_limit_proceeds(self):
        c = _make_confluence_connector(extra={"max_attachment_mb": 10})
        att = {**_ATTACHMENT, "extensions": {"fileSize": 9 * 1024 * 1024}}
        new_doc = {**_BASE_ATT_DOC, "status": "fetching"}
        client = _make_client()
        client.get = MagicMock(return_value=self._make_download_response(b"x" * (9 * 1024 * 1024)))

        with (
            patch("infra.postgres.get_doc_by_source", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc),
            patch("infra.postgres.update_doc_fields"),
            patch("infra.s3.upload_object"),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            c._process_attachment(client, KB_ID, CONNECTOR_ID, att)

        mock_enqueue.assert_called_once()

    def test_unchanged_version_skips(self):
        c = _make_confluence_connector()
        existing_doc = {**_BASE_ATT_DOC, "content_version": "2"}
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source", return_value=existing_doc),
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            c._process_attachment(client, KB_ID, CONNECTOR_ID, _ATTACHMENT)

        mock_upload.assert_not_called()
        mock_enqueue.assert_not_called()

    def test_deleted_doc_is_refetched(self):
        c = _make_confluence_connector()
        deleted_doc = {**_BASE_ATT_DOC, "status": "deleted", "content_version": "2"}
        client = _make_client()
        client.get = MagicMock(return_value=self._make_download_response())

        with (
            patch("infra.postgres.get_doc_by_source", return_value=deleted_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object"),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            c._process_attachment(client, KB_ID, CONNECTOR_ID, _ATTACHMENT)

        statuses = [call.args[1].get("status") for call in mock_update.call_args_list if call.args[1].get("status")]
        assert "fetching" in statuses
        mock_enqueue.assert_called_once()

    def test_download_failure_sets_failed(self):
        c = _make_confluence_connector()
        new_doc = {**_BASE_ATT_DOC, "status": "fetching"}
        client = _make_client()
        client.get = MagicMock(side_effect=httpx.ConnectError("timeout"))

        with (
            patch("infra.postgres.get_doc_by_source", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            c._process_attachment(client, KB_ID, CONNECTOR_ID, _ATTACHMENT)

        statuses = [call.args[1].get("status") for call in mock_update.call_args_list if call.args[1].get("status")]
        assert "failed" in statuses
        mock_upload.assert_not_called()
        mock_enqueue.assert_not_called()

    def test_s3_failure_sets_failed(self):
        c = _make_confluence_connector()
        new_doc = {**_BASE_ATT_DOC, "status": "fetching"}
        client = _make_client()
        client.get = MagicMock(return_value=self._make_download_response())

        with (
            patch("infra.postgres.get_doc_by_source", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object", side_effect=Exception("S3 error")),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            c._process_attachment(client, KB_ID, CONNECTOR_ID, _ATTACHMENT)

        statuses = [call.args[1].get("status") for call in mock_update.call_args_list if call.args[1].get("status")]
        assert "failed" in statuses
        mock_enqueue.assert_not_called()

    def test_all_supported_extensions_accepted(self):
        from pipeline.ops.parse import SUPPORTED_EXTENSIONS

        c = _make_confluence_connector()
        client = _make_client()
        client.get = MagicMock(return_value=self._make_download_response(b"content"))

        for ext in SUPPORTED_EXTENSIONS:
            att = {**_ATTACHMENT, "title": f"file{ext}"}
            new_doc = {**_BASE_ATT_DOC, "doc_type": ext.lstrip(".")}
            with (
                patch("infra.postgres.get_doc_by_source", return_value=None),
                patch("infra.postgres.create_doc", return_value=new_doc),
                patch("infra.postgres.update_doc_fields"),
                patch("infra.s3.upload_object"),
                patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            ):
                c._process_attachment(client, KB_ID, CONNECTOR_ID, att)
            mock_enqueue.assert_called_once()


# ──────────────────────────────────────────────
# _dispatch_sync wiring
# ──────────────────────────────────────────────

class TestDispatchSync:

    def test_confluence_connector_dispatched(self):
        from api.routers.connectors import _dispatch_sync

        connector = {
            "connector_id": CONNECTOR_ID,
            "kb_id": KB_ID,
            "source_type": "confluence",
            "config": {"base_url": BASE_URL_CLOUD, "space_key": SPACE_KEY},
        }

        with patch("connectors.confluence.ConfluenceConnector.sync") as mock_sync:
            _dispatch_sync(connector)

        mock_sync.assert_called_once_with(KB_ID, CONNECTOR_ID)


# ──────────────────────────────────────────────
# sync — pagination and iteration
# ──────────────────────────────────────────────

class TestSync:

    def test_sync_processes_all_pages(self):
        c = _make_confluence_connector()
        pages = [
            {**_PAGE, "id": "p1", "title": "Page 1"},
            {**_PAGE, "id": "p2", "title": "Page 2"},
        ]

        with (
            patch.object(c, "_iter_pages", return_value=iter(pages)),
            patch.object(c, "_process_page") as mock_process,
        ):
            c.sync(KB_ID, CONNECTOR_ID)

        assert mock_process.call_count == 2

    def test_attachment_list_api_failure_is_isolated(self):
        """Attachment list failure should not stop remaining attachments/pages."""
        c = _make_confluence_connector()
        client = _make_client()

        with (
            patch("infra.postgres.get_doc_by_source", return_value=None),
            patch("infra.postgres.create_doc", return_value={**_BASE_PAGE_DOC, "status": "fetching"}),
            patch("infra.postgres.update_doc_fields"),
            patch("infra.s3.upload_object"),
            patch("pipeline.enqueue.enqueue_upload_event"),
            patch.object(
                c, "_iter_attachments", side_effect=Exception("attachment API down")
            ),
        ):
            # Should not raise — exception is caught inside _process_page_attachments.
            c._process_page(client, KB_ID, CONNECTOR_ID, _PAGE)
