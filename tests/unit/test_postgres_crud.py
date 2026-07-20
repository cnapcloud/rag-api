"""Unit tests for infra/postgres.py — new doc_id-based document CRUD."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

import rag_api.infra.postgres as pg
from rag_api.exceptions import ConfigError

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

_NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
_DOC_ID = str(uuid.uuid4())
_KB_ID = "kb-test"
_SOURCE_URI = "test-doc.pdf"
_SOURCE = "test-doc.pdf"
_SOURCE_TYPE = "s3"


def _make_doc_row(
    doc_id: str = _DOC_ID,
    kb_id: str = _KB_ID,
    title: str = _SOURCE,
    source_type: str = _SOURCE_TYPE,
    source: str = _SOURCE_URI,
    storage_key: str | None = "kb-test/test-doc.pdf",
    content_version: str | None = "abc123",
    connector_id: str | None = None,
    status: str = "pending",
    deleted_at=None,
    run_id: str = "",
    last_error=None,
    created_at=_NOW,
    updated_at=_NOW,
    process_started_at=None,
    process_finished_at=None,
    chunk_count=None,
    file_size=None,
    doc_type: str | None = "pdf",
    embedding_model=None,
    doc_created_at=None,
    title_hash=None,
    content_simhash=None,
) -> tuple:
    """Build a tuple matching _DOC_COLS order."""
    return (
        doc_id, kb_id, title, source_type, source, storage_key,
        content_version, connector_id, status, deleted_at, run_id, last_error,
        created_at, updated_at, process_started_at, process_finished_at,
        chunk_count, file_size, doc_type, embedding_model, doc_created_at,
        title_hash, content_simhash,
    )


@contextmanager
def _fake_pool(fetchone_row=None, fetchall_rows=None):
    """Context manager that patches get_pool() with a mock returning preset rows."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_row
    cursor.fetchall.return_value = fetchall_rows or []
    cursor.__iter__ = lambda self: iter(fetchall_rows or [])

    conn = MagicMock()
    conn.execute.return_value = cursor

    pool = MagicMock()
    pool.connection.return_value.__enter__ = lambda s: conn
    pool.connection.return_value.__exit__ = MagicMock(return_value=False)

    with patch("rag_api.infra.postgres.get_pool", return_value=pool):
        yield conn, cursor


# ──────────────────────────────────────────────
# create_doc
# ──────────────────────────────────────────────

def test_create_doc_returns_dict():
    row = _make_doc_row()
    with _fake_pool(fetchone_row=row) as (conn, _):
        result = pg.create_doc(
            _KB_ID, _SOURCE_URI, _SOURCE, _SOURCE_TYPE,
            status="uploading", storage_key="kb-test/test-doc.pdf",
            content_version="abc123", doc_type="pdf",
        )
    assert result["doc_id"] == _DOC_ID
    assert result["kb_id"] == _KB_ID
    assert result["status"] == "pending"
    assert result["source"] == _SOURCE_URI
    conn.commit.assert_called_once()


def test_create_doc_doc_id_is_string():
    row = _make_doc_row()
    with _fake_pool(fetchone_row=row):
        result = pg.create_doc(_KB_ID, _SOURCE_URI, _SOURCE, _SOURCE_TYPE)
    assert isinstance(result["doc_id"], str)


# ──────────────────────────────────────────────
# get_doc_by_id
# ──────────────────────────────────────────────

def test_get_doc_by_id_found():
    row = _make_doc_row(status="indexed")
    with _fake_pool(fetchone_row=row):
        result = pg.get_doc_by_id(_DOC_ID)
    assert result is not None
    assert result["status"] == "indexed"
    assert result["doc_id"] == _DOC_ID


def test_get_doc_by_id_not_found():
    with _fake_pool(fetchone_row=None):
        result = pg.get_doc_by_id("nonexistent-id")
    assert result is None


# ──────────────────────────────────────────────
# get_doc_by_source
# ──────────────────────────────────────────────

def test_get_doc_by_source_found():
    row = _make_doc_row()
    with _fake_pool(fetchone_row=row):
        result = pg.get_doc_by_source(_KB_ID, _SOURCE_URI)
    assert result is not None
    assert result["source"] == _SOURCE_URI


def test_get_doc_by_source_not_found():
    with _fake_pool(fetchone_row=None):
        result = pg.get_doc_by_source(_KB_ID, "missing.pdf")
    assert result is None


# ──────────────────────────────────────────────
# update_doc_fields
# ──────────────────────────────────────────────

def test_update_doc_fields_sets_updated_at():
    with _fake_pool() as (conn, _):
        pg.update_doc_fields(_DOC_ID, {"status": "running", "run_id": "run-001"})
    sql_call = conn.execute.call_args_list[0]
    sql = sql_call[0][0]
    assert "updated_at = NOW()" in sql
    assert "status = %s" in sql
    assert "run_id = %s" in sql
    conn.commit.assert_called_once()


def test_update_doc_fields_ignores_unknown_keys():
    with _fake_pool() as (conn, _):
        pg.update_doc_fields(_DOC_ID, {"status": "running", "INVALID_FIELD": "x"})
    sql_call = conn.execute.call_args_list[0]
    sql = sql_call[0][0]
    assert "INVALID_FIELD" not in sql


def test_update_doc_fields_noop_on_empty():
    with _fake_pool() as (conn, _):
        pg.update_doc_fields(_DOC_ID, {"INVALID_FIELD": "x"})
    conn.execute.assert_not_called()


# ──────────────────────────────────────────────
# soft_delete_doc
# ──────────────────────────────────────────────

def test_soft_delete_sets_status_and_deleted_at():
    with _fake_pool() as (conn, _):
        pg.soft_delete_doc(_DOC_ID)
    sql_call = conn.execute.call_args_list[0]
    sql = sql_call[0][0]
    assert "status = 'deleted'" in sql
    assert "deleted_at = NOW()" in sql
    assert "updated_at = NOW()" in sql
    conn.commit.assert_called_once()


# ──────────────────────────────────────────────
# update_connector
# ──────────────────────────────────────────────

_CONNECTOR_ROW: tuple[object, ...] = (
    "conn-01", "kb-test", "Docs", "web", {}, None, False, "idle", None,
    None, "active", None, _NOW, _NOW,
)


def test_update_connector_status_change_clears_last_error():
    with _fake_pool(fetchone_row=_CONNECTOR_ROW) as (conn, _):
        pg.update_connector("conn-01", {"status": "active"})
    sql, params = conn.execute.call_args_list[0][0]
    assert "last_error = NULL" in sql
    assert "status = %s" in sql


def test_update_connector_without_status_keeps_last_error():
    with _fake_pool(fetchone_row=_CONNECTOR_ROW) as (conn, _):
        pg.update_connector("conn-01", {"name": "New Name"})
    sql, _ = conn.execute.call_args_list[0][0]
    set_clause = sql.split("RETURNING")[0]
    assert "last_error" not in set_clause


# ──────────────────────────────────────────────
# set_connector_status
# ──────────────────────────────────────────────

def test_set_connector_status_error_stores_message():
    with _fake_pool() as (conn, _):
        pg.set_connector_status("conn-01", "error", error="boom")
    sql, params = conn.execute.call_args_list[0][0]
    assert "last_error = %s" in sql
    assert params == ["error", "boom", "conn-01"]
    conn.commit.assert_called_once()


def test_set_connector_status_error_truncates_message():
    with _fake_pool() as (conn, _):
        pg.set_connector_status("conn-01", "error", error="x" * 600)
    _, params = conn.execute.call_args_list[0][0]
    assert len(params[1]) == 500


def test_set_connector_status_non_error_clears_last_error():
    with _fake_pool() as (conn, _):
        pg.set_connector_status("conn-01", "active")
    sql, params = conn.execute.call_args_list[0][0]
    assert "last_error = NULL" in sql
    assert params == ["active", "conn-01"]


# ──────────────────────────────────────────────
# list_docs
# ──────────────────────────────────────────────

def test_list_docs_excludes_deleted_by_default():
    with _fake_pool(fetchall_rows=[]) as (conn, _):
        pg.list_docs(_KB_ID)
    sql_call = conn.execute.call_args_list[0]
    sql = sql_call[0][0]
    assert "status != 'deleted'" in sql


def test_list_docs_include_deleted_flag():
    with _fake_pool(fetchall_rows=[]) as (conn, _):
        pg.list_docs(_KB_ID, include_deleted=True)
    sql_call = conn.execute.call_args_list[0]
    sql = sql_call[0][0]
    assert "status != 'deleted'" not in sql


def test_list_docs_status_filter():
    with _fake_pool(fetchall_rows=[]) as (conn, _):
        pg.list_docs(_KB_ID, status_filter="indexed")
    sql_call = conn.execute.call_args_list[0]
    sql, params = sql_call[0][0], sql_call[0][1]
    assert "status = %s" in sql
    assert "indexed" in params


def test_list_docs_returns_dicts():
    rows = [_make_doc_row(status="indexed"), _make_doc_row(doc_id=str(uuid.uuid4()), status="pending")]
    with _fake_pool(fetchall_rows=rows):
        result = pg.list_docs(_KB_ID)
    assert len(result) == 2
    assert all(isinstance(d, dict) for d in result)
    assert all("doc_id" in d for d in result)


# ──────────────────────────────────────────────
# list_docs_paginated
# ──────────────────────────────────────────────

def test_list_docs_paginated_excludes_deleted_by_default():
    with _fake_pool(fetchone_row=(0,), fetchall_rows=[]) as (conn, cursor):
        # first execute = COUNT, second execute = data
        cursor.fetchone.side_effect = [(0,), None]
        pg.list_docs_paginated(_KB_ID, page=1, page_size=10)
    count_sql = conn.execute.call_args_list[0][0][0]
    assert "status != 'deleted'" in count_sql


def test_list_docs_paginated_include_deleted():
    with _fake_pool(fetchone_row=(0,), fetchall_rows=[]) as (conn, cursor):
        cursor.fetchone.side_effect = [(0,), None]
        pg.list_docs_paginated(_KB_ID, page=1, page_size=10, include_deleted=True)
    count_sql = conn.execute.call_args_list[0][0][0]
    assert "status != 'deleted'" not in count_sql


# ──────────────────────────────────────────────
# kb_settings_overrides — docs/internal/design/kb-settings-override.md
# ──────────────────────────────────────────────

def test_get_kb_settings_overrides_assembles_flat_dict():
    rows = [("ingestion.max_file_size_mb", 50), ("chunking.chunk_size", 512)]
    with _fake_pool(fetchall_rows=rows):
        result = pg.get_kb_settings_overrides(_KB_ID)
    assert result == {"ingestion.max_file_size_mb": 50, "chunking.chunk_size": 512}


def test_get_kb_settings_overrides_empty_when_no_rows():
    with _fake_pool(fetchall_rows=[]):
        result = pg.get_kb_settings_overrides(_KB_ID)
    assert result == {}


def test_upsert_kb_settings_override_uses_on_conflict_upsert():
    with _fake_pool() as (conn, _):
        pg.upsert_kb_settings_override(_KB_ID, "chunking.chunk_size", 512)
    sql = conn.execute.call_args_list[0][0][0]
    assert "ON CONFLICT (kb_id, key) DO UPDATE" in sql
    conn.commit.assert_called_once()


def test_delete_kb_settings_override_deletes_single_key():
    with _fake_pool() as (conn, _):
        pg.delete_kb_settings_override(_KB_ID, "chunking.chunk_size")
    sql, params = conn.execute.call_args_list[0][0]
    assert "DELETE FROM kb_settings_overrides" in sql
    assert params == [_KB_ID, "chunking.chunk_size"]
    conn.commit.assert_called_once()


def test_replace_kb_settings_overrides_deletes_then_bulk_inserts():
    with _fake_pool() as (conn, _):
        pg.replace_kb_settings_overrides(_KB_ID, {"chunking.chunk_size": 512, "dedup.enabled": False})
    delete_sql = conn.execute.call_args_list[0][0][0]
    assert "DELETE FROM kb_settings_overrides" in delete_sql
    cur = conn.cursor.return_value.__enter__.return_value
    cur.executemany.assert_called_once()
    conn.commit.assert_called_once()


def test_replace_kb_settings_overrides_empty_skips_bulk_insert():
    with _fake_pool() as (conn, _):
        pg.replace_kb_settings_overrides(_KB_ID, {})
    conn.cursor.assert_not_called()
    conn.commit.assert_called_once()


def test_clear_kb_settings_overrides_deletes_all_rows_for_kb():
    with _fake_pool() as (conn, _):
        pg.clear_kb_settings_overrides(_KB_ID)
    sql, params = conn.execute.call_args_list[0][0]
    assert "DELETE FROM kb_settings_overrides" in sql
    assert params == [_KB_ID]
    conn.commit.assert_called_once()


def test_run_migrations_missing_dir_raises_config_error():
    """A downstream image copying src/ without the sibling migrations/ dir must fail loudly,
    not silently apply zero migrations (Path.glob() on a missing dir yields no error)."""
    with (
        patch("rag_api.infra.postgres.Path.is_dir", return_value=False),
        patch("rag_api.infra.postgres.get_pool") as mock_get_pool,
    ):
        with pytest.raises(ConfigError, match="Migrations directory not found"):
            pg.run_migrations()
    mock_get_pool.assert_not_called()
