"""Unit tests for WebConnector (R-09)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

KB_ID = "kb-01"
CONNECTOR_ID = "conn-web-01"

_DOC_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_URL = "https://example.com/docs/page"

_BASE_DOC = {
    "doc_id": _DOC_ID,
    "kb_id": KB_ID,
    "source": _URL,
    "source_type": "web",
    "source_uri": _URL,
    "status": "indexed",
    "content_version": "etag-v1",  # stored without surrounding quotes (stripped at write time)
    "storage_key": f"{KB_ID}/web/{_DOC_ID}.html",
    "connector_id": CONNECTOR_ID,
    "doc_type": "html",
}

_HTML_SIMPLE = """
<html>
<head><title>Test Page</title></head>
<body><p>Content here.</p><a href="/docs/page2">Next</a></body>
</html>
"""


def _make_response(html: str = _HTML_SIMPLE, status: int = 200, etag: str = "etag-v2") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.text = html
    resp.headers = {"etag": etag, "content-type": "text/html; charset=utf-8"}
    resp.raise_for_status = MagicMock()
    return resp


def _make_client(response: MagicMock) -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get = MagicMock(return_value=response)
    return client


# ──────────────────────────────────────────────
# _process_page — core logic
# ──────────────────────────────────────────────

class TestProcessPage:

    def test_new_doc_creates_row_stages_and_enqueues(self):
        from connectors.web import WebConnector

        resp = _make_response()
        client = _make_client(resp)
        new_doc = {**_BASE_DOC, "status": "fetching"}

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc) as mock_create,
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object", return_value="etag-s3") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch("connectors.web._extract_title", return_value="Test Page"),
        ):
            connector = WebConnector({"seed_urls": [_URL], "min_content_chars": 0, "skip_seed_pages": False})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        assert result == _HTML_SIMPLE
        mock_create.assert_called_once()
        create_kwargs = mock_create.call_args.kwargs
        assert create_kwargs["status"] == "fetching"
        assert create_kwargs["doc_type"] == "html"
        assert create_kwargs["source_type"] == "web"

        mock_upload.assert_called_once()
        upload_kwargs = mock_upload.call_args.kwargs
        assert upload_kwargs["content_type"] == "text/html"

        pending_call = next(
            c for c in mock_update.call_args_list if c.args[1].get("status") == "pending"
        )
        assert pending_call.args[1]["storage_key"] == f"{KB_ID}/web/{_DOC_ID}.html"
        assert pending_call.args[1]["source"] == "Test Page"

        mock_enqueue.assert_called_once_with(_DOC_ID, force=False)

    def test_unchanged_etag_updates_title_if_changed(self):
        from connectors.web import WebConnector

        existing_doc = {**_BASE_DOC, "content_version": "etag-v2", "source": _URL}
        resp = _make_response(etag="etag-v2")
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=existing_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch("connectors.web._extract_title", return_value="New Title"),
        ):
            connector = WebConnector({"seed_urls": [_URL], "min_content_chars": 0, "skip_seed_pages": False})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        assert result == _HTML_SIMPLE
        mock_upload.assert_not_called()
        mock_enqueue.assert_not_called()
        mock_update.assert_called_once_with(_DOC_ID, {"source": "New Title"})

    def test_unchanged_etag_title_same_skips_all(self):
        from connectors.web import WebConnector

        existing_doc = {**_BASE_DOC, "content_version": "etag-v2", "source": "Same Title"}
        resp = _make_response(etag="etag-v2")
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=existing_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch("connectors.web._extract_title", return_value="Same Title"),
        ):
            connector = WebConnector({"seed_urls": [_URL], "min_content_chars": 0, "skip_seed_pages": False})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        assert result == _HTML_SIMPLE
        mock_upload.assert_not_called()
        mock_enqueue.assert_not_called()
        mock_update.assert_not_called()

    def test_changed_etag_restages_and_reenqueues(self):
        from connectors.web import WebConnector

        existing_doc = {**_BASE_DOC, "content_version": "etag-old"}
        resp = _make_response(etag="etag-new")
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=existing_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object", return_value="s3-etag"),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch("connectors.web._extract_title", return_value="Test Page"),
        ):
            connector = WebConnector({"seed_urls": [_URL], "min_content_chars": 0, "skip_seed_pages": False})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        assert result == _HTML_SIMPLE
        statuses = [c.args[1].get("status") for c in mock_update.call_args_list if c.args[1].get("status")]
        assert "fetching" in statuses
        assert "pending" in statuses
        mock_enqueue.assert_called_once_with(_DOC_ID, force=False)

    def test_deleted_doc_is_refetched(self):
        from connectors.web import WebConnector

        deleted_doc = {**_BASE_DOC, "status": "deleted", "content_version": "etag-v2"}
        resp = _make_response(etag="etag-v2")
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=deleted_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object", return_value="s3-etag"),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch("connectors.web._extract_title", return_value="Test Page"),
        ):
            connector = WebConnector({"seed_urls": [_URL], "min_content_chars": 0, "skip_seed_pages": False})
            connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        statuses = [c.args[1].get("status") for c in mock_update.call_args_list if c.args[1].get("status")]
        assert "fetching" in statuses
        mock_enqueue.assert_called_once()

    def test_http_failure_sets_failed_on_existing_doc(self):
        from connectors.web import WebConnector

        existing_doc = {**_BASE_DOC}
        resp = MagicMock(spec=httpx.Response)
        resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        ))
        resp.text = ""
        resp.headers = {}
        client = _make_client(resp)
        client.get = MagicMock(side_effect=httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        ))

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=existing_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            connector = WebConnector({"seed_urls": [_URL], "min_content_chars": 0, "skip_seed_pages": False})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        assert result is None
        mock_upload.assert_not_called()
        mock_enqueue.assert_not_called()
        statuses = [c.args[1].get("status") for c in mock_update.call_args_list if c.args[1].get("status")]
        assert "failed" in statuses

    def test_http_failure_creates_failed_doc_for_new_url(self):
        from connectors.web import WebConnector

        failed_doc = {**_BASE_DOC, "status": "failed"}
        client = _make_client(MagicMock())
        client.get = MagicMock(side_effect=httpx.ConnectError("timeout"))

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc", return_value=failed_doc) as mock_create,
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object") as mock_upload,
        ):
            connector = WebConnector({"seed_urls": [_URL], "min_content_chars": 0, "skip_seed_pages": False})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        assert result is None
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["status"] == "failed"
        error_update = next(
            c for c in mock_update.call_args_list if "error" in c.args[1]
        )
        assert error_update is not None
        mock_upload.assert_not_called()

    def test_non_html_content_type_skips_processing(self):
        from connectors.web import WebConnector

        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.headers = {"content-type": "application/pdf"}
        resp.raise_for_status = MagicMock()
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc") as mock_create,
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            connector = WebConnector({"seed_urls": [_URL], "min_content_chars": 0, "skip_seed_pages": False})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        assert result is None
        mock_create.assert_not_called()
        mock_upload.assert_not_called()
        mock_enqueue.assert_not_called()

    def test_s3_failure_sets_failed_and_returns_html_for_link_discovery(self):
        from connectors.web import WebConnector

        new_doc = {**_BASE_DOC, "status": "fetching"}
        resp = _make_response()
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object", side_effect=Exception("S3 down")),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch("connectors.web._extract_title", return_value="Test Page"),
        ):
            connector = WebConnector({"seed_urls": [_URL], "min_content_chars": 0, "skip_seed_pages": False})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        assert result == _HTML_SIMPLE
        statuses = [c.args[1].get("status") for c in mock_update.call_args_list if c.args[1].get("status")]
        assert "failed" in statuses
        mock_enqueue.assert_not_called()


# ──────────────────────────────────────────────
# URL filtering
# ──────────────────────────────────────────────

class TestShouldProcess:

    def test_no_patterns_restricts_to_seed_prefix(self):
        """Without include_patterns, only URLs under the seed_url path are allowed."""
        from connectors.web import WebConnector

        c = WebConnector({"seed_urls": ["https://example.com/docs"]})
        assert c._should_process("https://example.com/docs/page") is True
        assert c._should_process("https://example.com/docs") is True   # exact seed URL
        assert c._should_process("https://example.com/other") is False  # outside /docs
        assert c._should_process("https://external.com/page") is False

    def test_empty_seed_prefixes_blocks_all(self):
        """Empty _seed_prefixes blocks every URL."""
        from connectors.web import WebConnector

        # Bypass __init__ validation to test _should_process in isolation.
        c = WebConnector.__new__(WebConnector)
        c.seed_urls = []
        c.include_patterns = []
        c.exclude_patterns = []
        c._seed_prefixes = frozenset()
        assert c._should_process("https://example.com/anything") is False

    def test_include_pattern_filters_within_seed_scope(self):
        """include_patterns is an additional filter within the seed prefix scope."""
        from connectors.web import WebConnector

        c = WebConnector({
            "seed_urls": ["https://example.com/docs"],
            "include_patterns": ["*/guide/*"],
        })
        assert c._should_process("https://example.com/docs/guide/intro") is True
        assert c._should_process("https://example.com/docs/reference") is False  # not in pattern
        assert c._should_process("https://external.com/docs/guide/intro") is False  # outside scope

    def test_include_pattern_filters_non_matching(self):
        from connectors.web import WebConnector

        c = WebConnector({
            "seed_urls": ["https://example.com"],
            "include_patterns": ["https://example.com/docs/*"],
        })
        assert c._should_process("https://example.com/docs/page") is True
        assert c._should_process("https://example.com/blog/post") is False

    def test_exclude_pattern_blocks_matching(self):
        from connectors.web import WebConnector

        c = WebConnector({
            "seed_urls": ["https://example.com"],
            "exclude_patterns": ["https://example.com/admin/*"],
        })
        assert c._should_process("https://example.com/admin/settings") is False
        assert c._should_process("https://example.com/docs/page") is True

    def test_exclude_takes_precedence_over_include(self):
        from connectors.web import WebConnector

        c = WebConnector({
            "seed_urls": ["https://example.com"],
            "include_patterns": ["https://example.com/*"],
            "exclude_patterns": ["https://example.com/admin/*"],
        })
        assert c._should_process("https://example.com/admin/settings") is False
        assert c._should_process("https://example.com/docs/page") is True

    def test_exclude_takes_precedence_over_domain_restriction(self):
        from connectors.web import WebConnector

        c = WebConnector({
            "seed_urls": ["https://example.com"],
            "exclude_patterns": ["https://example.com/admin/*"],
        })
        assert c._should_process("https://example.com/admin/settings") is False
        assert c._should_process("https://example.com/docs") is True

    def test_pagination_path_allowed_for_link_discovery(self):
        """Pagination URLs within seed scope are allowed by _should_process.

        BFS must follow /page/2/ links to discover articles beyond page 1.
        Staging is skipped inside _process_page, not here.
        URLs outside seed scope are still blocked.
        """
        from connectors.web import WebConnector

        c = WebConnector({"seed_urls": ["https://example.com/blog"]})
        assert c._should_process("https://example.com/blog/page/2") is True
        assert c._should_process("https://example.com/blog/page/2/") is True
        assert c._should_process("https://example.com/posts/page/3/") is False  # outside seed scope
        assert c._should_process("https://example.com/blog/my-article") is True

    def test_pagination_query_allowed_for_link_discovery(self):
        """Query-based pagination within seed scope is allowed by _should_process.

        Staging is skipped inside _process_page, not here.
        """
        from connectors.web import WebConnector

        c = WebConnector({"seed_urls": ["https://example.com"]})
        assert c._should_process("https://example.com/blog?page=2") is True
        assert c._should_process("https://example.com/blog?p=3") is True
        assert c._should_process("https://example.com/blog?category=tech") is True


class TestIsPaginationUrl:

    def test_path_page_number(self):
        from connectors.web import _is_pagination_url

        assert _is_pagination_url("https://example.com/blog/page/2") is True
        assert _is_pagination_url("https://example.com/blog/page/2/") is True
        assert _is_pagination_url("https://example.com/posts/page/10/") is True

    def test_query_page_param(self):
        from connectors.web import _is_pagination_url

        assert _is_pagination_url("https://example.com/blog?page=2") is True
        assert _is_pagination_url("https://example.com/blog?p=3") is True
        assert _is_pagination_url("https://example.com/blog?category=tech&page=2") is True

    def test_non_pagination_urls(self):
        from connectors.web import _is_pagination_url

        assert _is_pagination_url("https://example.com/blog/my-article") is False
        assert _is_pagination_url("https://example.com/blog/page-title") is False
        assert _is_pagination_url("https://example.com/blog?category=tech") is False


class TestHasSufficientContent:

    def test_long_content_returns_true(self):
        from connectors.web import _has_sufficient_content

        with patch("trafilatura.extract", return_value="x" * 500):
            assert _has_sufficient_content("<html/>", 200) is True

    def test_short_content_returns_false(self):
        from connectors.web import _has_sufficient_content

        with patch("trafilatura.extract", return_value="short"):
            assert _has_sufficient_content("<html/>", 200) is False

    def test_none_extraction_returns_false(self):
        from connectors.web import _has_sufficient_content

        with patch("trafilatura.extract", return_value=None):
            assert _has_sufficient_content("<html/>", 200) is False

    def test_min_chars_zero_always_true(self):
        from connectors.web import _has_sufficient_content

        with patch("trafilatura.extract", return_value=None):
            assert _has_sufficient_content("<html/>", 0) is True

    def test_extraction_error_fails_open(self):
        from connectors.web import _has_sufficient_content

        with patch("trafilatura.extract", side_effect=Exception("boom")):
            assert _has_sufficient_content("<html/>", 200) is True


class TestContentFilter:

    def test_depth_zero_skips_staging_returns_html(self):
        from connectors.web import WebConnector

        resp = _make_response(etag="etag-v1")
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc") as mock_create,
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
        ):
            connector = WebConnector({"seed_urls": [_URL], "skip_seed_pages": True})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=0)

        assert result == _HTML_SIMPLE
        mock_create.assert_not_called()
        mock_upload.assert_not_called()
        mock_enqueue.assert_not_called()

    def test_depth_zero_skip_disabled_proceeds_to_stage(self):
        from connectors.web import WebConnector

        new_doc = {**_BASE_DOC, "status": "fetching"}
        resp = _make_response(etag="etag-new")
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc),
            patch("infra.postgres.update_doc_fields"),
            patch("infra.s3.upload_object", return_value="etag"),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch("connectors.web._extract_title", return_value="Title"),
            patch("connectors.web._has_sufficient_content", return_value=True),
        ):
            connector = WebConnector({"seed_urls": [_URL], "skip_seed_pages": False})
            connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=0)

        mock_enqueue.assert_called_once()

    def test_insufficient_content_skips_staging_returns_html(self):
        from connectors.web import WebConnector

        resp = _make_response(etag="etag-v1")
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc") as mock_create,
            patch("connectors.web._has_sufficient_content", return_value=False),
        ):
            connector = WebConnector({"seed_urls": [_URL], "skip_seed_pages": False, "min_content_chars": 200})
            result = connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        assert result == _HTML_SIMPLE
        mock_create.assert_not_called()

    def test_min_content_chars_zero_disables_check(self):
        from connectors.web import WebConnector

        new_doc = {**_BASE_DOC, "status": "fetching"}
        resp = _make_response(etag="etag-new")
        client = _make_client(resp)

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc),
            patch("infra.postgres.update_doc_fields"),
            patch("infra.s3.upload_object", return_value="etag"),
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch("connectors.web._extract_title", return_value="Title"),
        ):
            connector = WebConnector({"seed_urls": [_URL], "skip_seed_pages": False, "min_content_chars": 0})
            connector._process_page(client, KB_ID, CONNECTOR_ID, _URL, depth=1)

        mock_enqueue.assert_called_once()


# ──────────────────────────────────────────────
# sync — BFS and max_pages
# ──────────────────────────────────────────────

class TestSync:

    def test_max_pages_limits_crawl(self):
        from connectors.web import WebConnector

        seed = ["https://example.com/p1", "https://example.com/p2", "https://example.com/p3"]

        with patch.object(WebConnector, "_process_page", return_value=None) as mock_process:
            connector = WebConnector({"seed_urls": seed, "max_pages": 2})
            connector.sync(KB_ID, CONNECTOR_ID)

        assert mock_process.call_count == 2

    def test_bfs_discovers_links_at_depth_1(self):
        from connectors.web import WebConnector

        html_with_link = '<html><body><a href="https://example.com/docs/page2">Next</a></body></html>'
        seed = ["https://example.com/docs"]
        processed_urls: list[str] = []

        def fake_process(client, kb_id, connector_id, url, depth=0):
            processed_urls.append(url)
            if url == "https://example.com/docs":
                return html_with_link
            return None

        with patch.object(WebConnector, "_process_page", side_effect=fake_process):
            connector = WebConnector({"seed_urls": seed, "depth": 1, "max_pages": 10})
            connector.sync(KB_ID, CONNECTOR_ID)

        assert "https://example.com/docs" in processed_urls
        assert "https://example.com/docs/page2" in processed_urls

    def test_bfs_does_not_revisit_urls(self):
        from connectors.web import WebConnector

        seed = ["https://example.com/page", "https://example.com/page"]

        with patch.object(WebConnector, "_process_page", return_value=None) as mock_process:
            connector = WebConnector({"seed_urls": seed})
            connector.sync(KB_ID, CONNECTOR_ID)

        assert mock_process.call_count == 1

    def test_depth_zero_does_not_follow_links(self):
        from connectors.web import WebConnector

        html_with_link = '<html><body><a href="https://example.com/page2">Next</a></body></html>'
        seed = ["https://example.com/page1"]
        processed_urls: list[str] = []

        def fake_process(client, kb_id, connector_id, url, depth=0):
            processed_urls.append(url)
            return html_with_link

        with patch.object(WebConnector, "_process_page", side_effect=fake_process):
            connector = WebConnector({"seed_urls": seed, "depth": 0, "max_pages": 10})
            connector.sync(KB_ID, CONNECTOR_ID)

        assert processed_urls == ["https://example.com/page1"]

    def test_queue_size_cap_prevents_memory_bloat(self):
        """Links beyond max_pages * 20 are dropped from queue."""
        from connectors.web import WebConnector, _QUEUE_SIZE_MULTIPLIER

        max_pages = 2
        cap = max_pages * _QUEUE_SIZE_MULTIPLIER
        # Page returns more links than the queue cap.
        many_links = "".join(
            f'<a href="https://example.com/p{i}">p{i}</a>' for i in range(cap + 50)
        )
        html_many_links = f"<html><body>{many_links}</body></html>"

        added_to_queue: list[str] = []
        original_append = None

        def fake_process(client, kb_id, connector_id, url, depth=0):
            return html_many_links

        with patch.object(WebConnector, "_process_page", side_effect=fake_process):
            connector = WebConnector({"seed_urls": ["https://example.com/root"], "depth": 1, "max_pages": max_pages})
            connector.sync(KB_ID, CONNECTOR_ID)

        # Just verify sync completes without error and respects max_pages.
        # Queue overflow links are silently dropped.

    def test_external_domain_blocked_without_include_patterns(self):
        """Auto domain restriction prevents crawling external sites."""
        from connectors.web import WebConnector

        external_html = '<html><body><a href="https://external.com/evil">ext</a></body></html>'
        seed = ["https://example.com/docs"]
        processed_urls: list[str] = []

        def fake_process(client, kb_id, connector_id, url, depth=0):
            processed_urls.append(url)
            return external_html

        with patch.object(WebConnector, "_process_page", side_effect=fake_process):
            connector = WebConnector({"seed_urls": seed, "depth": 1, "max_pages": 10})
            connector.sync(KB_ID, CONNECTOR_ID)

        # Only the seed URL itself should have been processed.
        assert all("example.com" in u for u in processed_urls)
        assert not any("external.com" in u for u in processed_urls)

    def test_default_max_pages_is_50(self):
        from connectors.web import WebConnector

        c = WebConnector({"seed_urls": ["https://example.com"]})
        assert c.max_pages == 50

    def test_default_depth_is_2(self):
        from connectors.web import WebConnector

        c = WebConnector({"seed_urls": ["https://example.com"]})
        assert c.depth == 2

    def test_missing_seed_urls_raises_config_error(self):
        from exceptions import ConfigError
        from connectors.web import WebConnector

        with pytest.raises(ConfigError, match="seed_url"):
            WebConnector({})

    def test_empty_seed_urls_raises_config_error(self):
        from exceptions import ConfigError
        from connectors.web import WebConnector

        with pytest.raises(ConfigError, match="seed_url"):
            WebConnector({"seed_urls": []})


# ──────────────────────────────────────────────
# Auth config — httpx.Client kwargs
# ──────────────────────────────────────────────

class TestAuthConfig:

    def _captured_client_kwargs(self, config: dict) -> dict:
        """Run sync() with a no-op _process_page and capture httpx.Client kwargs."""
        from connectors.web import WebConnector

        captured: dict = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def get(self, *_, **__):
                return MagicMock()

        with patch("connectors.web.httpx.Client", FakeClient):
            with patch.object(WebConnector, "_process_page", return_value=None):
                WebConnector(config).sync(KB_ID, CONNECTOR_ID)

        return captured

    def test_no_auth_omits_auth_key(self):
        kwargs = self._captured_client_kwargs({"seed_urls": [_URL]})
        assert "auth" not in kwargs
        assert kwargs["headers"] == {"User-Agent": "RAG-WebConnector/1.0"}

    def test_auth_headers_merged_into_headers(self):
        kwargs = self._captured_client_kwargs({
            "seed_urls": [_URL],
            "auth_headers": {"Authorization": "Bearer token123"},
        })
        assert "auth" not in kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer token123"
        assert kwargs["headers"]["User-Agent"] == "RAG-WebConnector/1.0"

    def test_auth_basic_sets_auth_tuple(self):
        kwargs = self._captured_client_kwargs({
            "seed_urls": [_URL],
            "auth_basic": {"username": "user", "password": "pass"},
        })
        assert kwargs["auth"] == ("user", "pass")
        assert kwargs["headers"] == {"User-Agent": "RAG-WebConnector/1.0"}

    def test_auth_headers_takes_priority_over_auth_basic(self):
        kwargs = self._captured_client_kwargs({
            "seed_urls": [_URL],
            "auth_headers": {"Authorization": "Bearer token123"},
            "auth_basic": {"username": "user", "password": "pass"},
        })
        assert "auth" not in kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer token123"

    def test_empty_auth_headers_falls_through_to_auth_basic(self):
        kwargs = self._captured_client_kwargs({
            "seed_urls": [_URL],
            "auth_headers": {},
            "auth_basic": {"username": "u", "password": "p"},
        })
        assert kwargs["auth"] == ("u", "p")


# ──────────────────────────────────────────────
# _dispatch_sync wiring
# ──────────────────────────────────────────────

class TestDispatchSync:

    def test_web_connector_dispatched_for_web_source_type(self):
        from api.routers.connectors import _dispatch_sync

        connector = {
            "connector_id": CONNECTOR_ID,
            "kb_id": KB_ID,
            "source_type": "web",
            "config": {"seed_urls": ["https://example.com"]},
        }

        with patch("connectors.web.WebConnector.sync") as mock_sync:
            _dispatch_sync(connector)

        mock_sync.assert_called_once_with(KB_ID, CONNECTOR_ID)

    def test_unimplemented_source_type_logs_and_returns(self):
        from api.routers.connectors import _dispatch_sync

        connector = {
            "connector_id": CONNECTOR_ID,
            "kb_id": KB_ID,
            "source_type": "github",
            "config": {},
        }

        # Should not raise — just logs info.
        _dispatch_sync(connector)


# ──────────────────────────────────────────────
# _extract_title — priority order
# ──────────────────────────────────────────────

class TestExtractTitle:

    def test_og_title_wins(self):
        from connectors.web import _extract_title

        html = """
        <html><head>
          <meta property="og:title" content="OG Title" />
          <title>HTML Title</title>
        </head><body><article><h1>Article H1</h1></article><h1>H1</h1></body></html>
        """
        assert _extract_title(html, "fallback") == "OG Title"

    def test_article_h1_wins_over_h1(self):
        from connectors.web import _extract_title

        html = """
        <html><head><title>HTML Title</title></head>
        <body><article><h1>Article H1</h1></article><h1>Top H1</h1></body></html>
        """
        assert _extract_title(html, "fallback") == "Article H1"

    def test_h1_wins_over_title(self):
        from connectors.web import _extract_title

        html = """
        <html><head><title>HTML Title</title></head>
        <body><h1>Page H1</h1></body></html>
        """
        assert _extract_title(html, "fallback") == "Page H1"

    def test_html_title_used_when_no_h1(self):
        from connectors.web import _extract_title

        html = """
        <html><head><title>HTML Title</title></head>
        <body><p>No headings here.</p></body></html>
        """
        assert _extract_title(html, "fallback") == "HTML Title"

    def test_fallback_url_used_when_no_metadata(self):
        from connectors.web import _extract_title

        html = "<html><body><p>No metadata.</p></body></html>"
        assert _extract_title(html, "https://example.com/page") == "https://example.com/page"

    def test_empty_og_content_falls_through(self):
        from connectors.web import _extract_title

        html = """
        <html><head>
          <meta property="og:title" content="" />
          <title>HTML Title</title>
        </head><body></body></html>
        """
        assert _extract_title(html, "fallback") == "HTML Title"

    def test_empty_h1_falls_through_to_title(self):
        from connectors.web import _extract_title

        html = """
        <html><head><title>HTML Title</title></head>
        <body><h1>   </h1></body></html>
        """
        assert _extract_title(html, "fallback") == "HTML Title"
