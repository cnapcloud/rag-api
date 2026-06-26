"""Unit tests for GitHubConnector (R-11)."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import httpx
import pytest

KB_ID = "kb-01"
CONNECTOR_ID = "conn-gh-01"
OWNER = "my-org"
REPO = "my-repo"
BRANCH = "main"

_FILE_PATH = "src/main.py"
_FILE_SHA = "abc123def456"
_FILE_SIZE = 1024
_DOC_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_SOURCE_URI = f"https://github.com/{OWNER}/{REPO}/blob/{BRANCH}/{_FILE_PATH}"
_STORAGE_KEY = f"{KB_ID}/github/{_DOC_ID}.py"

_TREE_SHA = "tree-sha-001"
_COMMIT_SHA = "commit-sha-001"

_BRANCH_RESPONSE = {
    "name": BRANCH,
    "commit": {
        "sha": _COMMIT_SHA,
        "commit": {"tree": {"sha": _TREE_SHA}},
    },
}

_TREE_RESPONSE = {
    "sha": _TREE_SHA,
    "tree": [
        {"path": _FILE_PATH, "type": "blob", "sha": _FILE_SHA, "size": _FILE_SIZE},
        {"path": "README.md", "type": "blob", "sha": "readme-sha", "size": 200},
        {"path": "src/", "type": "tree", "sha": "tree-sha-src", "size": 0},
        {"path": "data/big.bin", "type": "blob", "sha": "bin-sha", "size": 999_999_999},
    ],
    "truncated": False,
}

_CONTENTS_RESPONSE = {
    "path": _FILE_PATH,
    "sha": _FILE_SHA,
    "size": _FILE_SIZE,
    "content": "cHJpbnQoImhlbGxvIik=",  # base64("print(\"hello\")")
    "download_url": f"https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/{_FILE_PATH}",
}

_BASE_DOC = {
    "doc_id": _DOC_ID,
    "kb_id": KB_ID,
    "source": _FILE_PATH,
    "source_type": "github",
    "source_uri": _SOURCE_URI,
    "status": "indexed",
    "content_version": _FILE_SHA,
    "storage_key": _STORAGE_KEY,
    "connector_id": CONNECTOR_ID,
    "doc_type": "py",
}


def _make_connector(extra: dict | None = None):
    from connectors.github import GitHubConnector

    config: dict = {
        "owner": OWNER,
        "repo": REPO,
        "branch": BRANCH,
        "request_delay_ms": 0,
    }
    config.update(extra or {})
    return GitHubConnector(config)


def _make_http_client() -> MagicMock:
    client = MagicMock(spec=httpx.Client)
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


def _json_response(data) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    return resp


# ─── Constructor ──────────────────────────────────────────────────────────────

class TestConstructor:
    def test_requires_owner(self):
        from exceptions import ConfigError

        with pytest.raises(ConfigError, match="owner"):
            _make_connector({"owner": ""})

    def test_requires_repo(self):
        from exceptions import ConfigError

        with pytest.raises(ConfigError, match="repo"):
            _make_connector({"repo": ""})

    def test_defaults(self):
        c = _make_connector()
        assert c.branch == "main"
        assert c.path_prefix == ""
        assert c.request_delay_ms == 0
        assert c._auth_header is None

    def test_auth_token_from_config(self):
        c = _make_connector({"auth_token_secret": "my-pat"})
        assert c._auth_header == "Bearer my-pat"


# ─── _iter_blobs ──────────────────────────────────────────────────────────────

class TestIterBlobs:
    def test_filters_by_supported_extensions(self):
        """Only .py and .md blobs pass (not .bin tree entries)."""
        connector = _make_connector()

        with patch.object(connector, "_api_get") as mock_get:
            mock_get.side_effect = [_BRANCH_RESPONSE, _TREE_RESPONSE]
            blobs = connector._iter_blobs(MagicMock())

        paths = [b["path"] for b in blobs]
        assert _FILE_PATH in paths       # .py — supported
        assert "README.md" in paths      # .md — supported
        assert "src/" not in paths       # tree entry — excluded
        assert "data/big.bin" not in paths  # .bin — not in SUPPORTED_EXTENSIONS

    def test_filters_by_path_prefix(self):
        """Only blobs under path_prefix are returned."""
        connector = _make_connector({"path_prefix": "src/"})

        with patch.object(connector, "_api_get") as mock_get:
            mock_get.side_effect = [_BRANCH_RESPONSE, _TREE_RESPONSE]
            blobs = connector._iter_blobs(MagicMock())

        paths = [b["path"] for b in blobs]
        assert paths == [_FILE_PATH]
        assert "README.md" not in paths

    def test_max_files_limits_result(self):
        """max_files=1 returns only the first matching blob."""
        connector = _make_connector({"max_files": 1})

        with patch.object(connector, "_api_get") as mock_get:
            mock_get.side_effect = [_BRANCH_RESPONSE, _TREE_RESPONSE]
            blobs = connector._iter_blobs(MagicMock())

        assert len(blobs) == 1


# ─── _process_file ────────────────────────────────────────────────────────────

class TestProcessFile:
    def _item(self, **kwargs) -> dict:
        base = {"path": _FILE_PATH, "sha": _FILE_SHA, "size": _FILE_SIZE, "type": "blob"}
        base.update(kwargs)
        return base

    def test_new_file_staged(self):
        connector = _make_connector()
        new_doc = {"doc_id": _DOC_ID}

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc) as mock_create,
            patch("infra.postgres.update_doc_fields"),
            patch("infra.s3.upload_object") as mock_upload,
            patch("pipeline.enqueue.enqueue_upload_event") as mock_enqueue,
            patch.object(connector, "_download_file", return_value=b'print("hello")'),
        ):
            connector._process_file(MagicMock(), KB_ID, CONNECTOR_ID, self._item())

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["source_type"] == "github"
        assert call_kwargs["doc_type"] == "py"
        assert call_kwargs["source_uri"] == _SOURCE_URI

        mock_upload.assert_called_once()
        mock_enqueue.assert_called_once_with(_DOC_ID, force=False)

    def test_unchanged_file_skipped(self):
        connector = _make_connector()
        existing = {**_BASE_DOC, "content_version": _FILE_SHA}

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=existing),
            patch.object(connector, "_download_file") as mock_dl,
        ):
            connector._process_file(MagicMock(), KB_ID, CONNECTOR_ID, self._item())

        mock_dl.assert_not_called()

    def test_too_large_file_skipped(self):
        connector = _make_connector({"max_file_size_mb": 1})
        item = self._item(size=10 * 1024 * 1024)  # 10 MB > 1 MB limit

        with patch("infra.postgres.get_doc_by_source_uri", return_value=None) as mock_get:
            connector._process_file(MagicMock(), KB_ID, CONNECTOR_ID, item)

        mock_get.assert_not_called()

    def test_download_failure_marks_failed(self):
        connector = _make_connector()
        new_doc = {"doc_id": _DOC_ID}

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=None),
            patch("infra.postgres.create_doc", return_value=new_doc),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch.object(connector, "_download_file", side_effect=RuntimeError("network error")),
        ):
            connector._process_file(MagicMock(), KB_ID, CONNECTOR_ID, self._item())

        mock_update.assert_called_once()
        update_fields = mock_update.call_args.args[1]
        assert update_fields["status"] == "failed"
        assert "network error" in update_fields["error"]

    def test_changed_file_reingest(self):
        """File with same source_uri but different SHA is re-ingested."""
        connector = _make_connector()
        existing = {**_BASE_DOC, "content_version": "old-sha", "status": "indexed"}

        with (
            patch("infra.postgres.get_doc_by_source_uri", return_value=existing),
            patch("infra.postgres.update_doc_fields") as mock_update,
            patch("infra.s3.upload_object"),
            patch("pipeline.enqueue.enqueue_upload_event"),
            patch.object(connector, "_download_file", return_value=b"new content"),
        ):
            connector._process_file(MagicMock(), KB_ID, CONNECTOR_ID, self._item())

        mock_update.assert_any_call(_DOC_ID, {"status": "fetching", "connector_id": CONNECTOR_ID})


# ─── chunk.py code routing ────────────────────────────────────────────────────

class TestChunkCodeRouting:
    def test_py_file_uses_code_strategy_metadata(self):
        """Documents with doc_type=py get chunk_strategy='code' in metadata."""
        from llama_index.core import Document
        from unittest.mock import patch as _patch

        from pipeline.ops.chunk import chunk

        doc = Document(text="def hello():\n    return 'world'\n" * 10, metadata={"doc_type": "py"})

        mock_node = MagicMock()
        mock_node.get_content.return_value = "def hello():\n    return 'world'"
        mock_node.metadata = {}

        mock_parser = MagicMock()
        mock_parser.get_nodes_from_documents.return_value = [mock_node]

        with _patch("pipeline.ops.chunk._build_code_parser", return_value=mock_parser) as mock_build:
            nodes = chunk([doc])

        mock_build.assert_called_once()
        assert mock_node.metadata.get("chunk_strategy") == "code"

    def test_pdf_file_uses_text_strategy(self):
        """Documents with doc_type=pdf use the configured text strategy."""
        from llama_index.core import Document
        from unittest.mock import patch as _patch

        from pipeline.ops.chunk import chunk

        doc = Document(text="sample text " * 200, metadata={"doc_type": "pdf"})

        with _patch("pipeline.ops.chunk._build_code_parser") as mock_code:
            nodes = chunk([doc], strategy="recursive", chunk_size=128, chunk_overlap=16)

        mock_code.assert_not_called()
        assert len(nodes) > 0
        assert all(n.metadata.get("chunk_strategy") == "recursive" for n in nodes)


# ─── parse.py CODE_EXTENSIONS ────────────────────────────────────────────────

class TestParseCodeExtensions:
    def test_code_extensions_subset_of_supported(self):
        from pipeline.ops.parse import CODE_EXTENSIONS, SUPPORTED_EXTENSIONS

        assert CODE_EXTENSIONS.issubset(SUPPORTED_EXTENSIONS)

    def test_code_language_map_covers_all_code_extensions(self):
        from pipeline.ops.parse import CODE_EXTENSIONS, CODE_LANGUAGE_MAP

        for ext in CODE_EXTENSIONS:
            assert ext in CODE_LANGUAGE_MAP, f"Missing language mapping for {ext}"
