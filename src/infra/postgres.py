"""Postgres connection pool, schema migrations, KB and document metadata CRUD."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import psycopg_pool

from config.settings import get_settings

logger = logging.getLogger(__name__)

_pool: psycopg_pool.ConnectionPool | None = None


def _to_local_iso(dt: datetime | None) -> str:
    """Convert a UTC-aware datetime to the server's local timezone ISO string."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().isoformat()


# Fields allowed in update_doc_fields() to prevent SQL injection via dict keys.
_ALLOWED_UPDATE_FIELDS = frozenset({
    "source", "storage_key", "content_version", "connector_id", "status",
    "deleted_at", "run_id", "error", "process_started_at", "process_finished_at",
    "chunk_count", "file_size", "doc_type", "embedding_model", "doc_created_at",
    "title_hash", "content_simhash",
})

_ALLOWED_SORT_FIELDS = frozenset({"updated_at", "created_at", "source", "chunk_count", "file_size"})
_NULL_LAST_FIELDS = frozenset({"chunk_count", "file_size"})

# Column order for all documents SELECT queries — must match CREATE TABLE order.
_DOC_COLS = (
    "doc_id", "kb_id", "source", "source_type", "source_uri", "storage_key",
    "content_version", "connector_id", "status", "deleted_at", "run_id", "error",
    "created_at", "updated_at", "process_started_at", "process_finished_at",
    "chunk_count", "file_size", "doc_type", "embedding_model", "doc_created_at",
    "title_hash", "content_simhash",
)
_DOC_SELECT = "SELECT " + ", ".join(_DOC_COLS) + " FROM documents"

_DATETIME_COLS = frozenset({
    "deleted_at", "created_at", "updated_at",
    "process_started_at", "process_finished_at", "doc_created_at",
})


def get_pool() -> psycopg_pool.ConnectionPool:
    global _pool
    if _pool is None:
        cfg = get_settings().postgres
        conninfo = (
            f"host={cfg.host} port={cfg.port} dbname={cfg.dbname} "
            f"user={cfg.user} password={cfg.password} "
            f"connect_timeout={cfg.connect_timeout}"
        )
        _pool = psycopg_pool.ConnectionPool(conninfo, min_size=1, max_size=cfg.pool_size, open=False)
        _pool.open(wait=True, timeout=cfg.connect_timeout)
    return _pool


def ping() -> bool:
    try:
        with get_pool().connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as e:
        logger.warning("Postgres ping failed: %s", e)
        return False


def run_migrations() -> None:
    """Apply pending SQL migration files (migrations/*.sql) in alphabetical order."""
    migration_dir = Path(__file__).parents[2] / "migrations"
    with get_pool().connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        for f in sorted(migration_dir.glob("*.sql")):
            if f.stem not in applied:
                conn.execute(f.read_text())
                conn.execute("INSERT INTO schema_migrations(version) VALUES (%s)", [f.stem])
                logger.info("Migration applied: %s", f.stem)
        conn.commit()


# ──────────────────────────────────────────────
# KB metadata
# ──────────────────────────────────────────────

def register_kb(
    kb_id: str,
    kb_name: str = "",
    description: str | None = None,
    tags: list[str] | None = None,
) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO knowledge_bases (kb_id, kb_name, description, tags) VALUES (%s, %s, %s, %s) ON CONFLICT (kb_id) DO NOTHING",
            [kb_id, kb_name, description, tags or []],
        )
        conn.commit()
    logger.info("KB registered: %s", kb_id)


def get_kb_meta(kb_id: str) -> dict | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT kb_id, kb_name, description, tags, status, created_at, updated_at FROM knowledge_bases WHERE kb_id = %s",
            [kb_id],
        ).fetchone()
    if row is None:
        return None
    return {
        "kb_id": row[0],
        "kb_name": row[1],
        "description": row[2],
        "tags": list(row[3]) if row[3] else [],
        "status": row[4],
        "created_at": _to_local_iso(row[5]),
        "updated_at": _to_local_iso(row[6]),
    }


def list_kb_ids() -> list[str]:
    with get_pool().connection() as conn:
        rows = conn.execute("SELECT kb_id FROM knowledge_bases ORDER BY kb_id").fetchall()
    return [r[0] for r in rows]


def update_kb_meta(
    kb_id: str,
    kb_name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> None:
    parts, params = [], []
    if kb_name is not None:
        parts.append("kb_name = %s")
        params.append(kb_name)
    if description is not None:
        parts.append("description = %s")
        params.append(description)
    if tags is not None:
        parts.append("tags = %s")
        params.append(tags)
    if not parts:
        return
    parts.append("updated_at = NOW()")
    params.append(kb_id)
    with get_pool().connection() as conn:
        conn.execute(
            f"UPDATE knowledge_bases SET {', '.join(parts)} WHERE kb_id = %s",
            params,
        )
        conn.commit()
    logger.info("KB meta updated: %s", kb_id)


def update_kb_status(kb_id: str, status: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE knowledge_bases SET status = %s WHERE kb_id = %s",
            [status, kb_id],
        )
        conn.commit()


def delete_kb_meta(kb_id: str) -> None:
    # ON DELETE CASCADE on documents.kb_id handles document cleanup automatically.
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM knowledge_bases WHERE kb_id = %s", [kb_id])
        conn.commit()
    logger.info("KB meta deleted: %s", kb_id)


# ──────────────────────────────────────────────
# Document metadata
# ──────────────────────────────────────────────

def _row_to_doc(row: tuple) -> dict:
    d = dict(zip(_DOC_COLS, row))
    d["doc_id"] = str(d["doc_id"]) if d["doc_id"] is not None else None
    for col in _DATETIME_COLS:
        if d[col] is not None:
            d[col] = _to_local_iso(d[col])
    return d


def create_doc(
    kb_id: str,
    source_uri: str,
    source: str,
    source_type: str,
    *,
    status: str = "pending",
    storage_key: str | None = None,
    content_version: str | None = None,
    connector_id: str | None = None,
    file_size: int | None = None,
    doc_type: str | None = None,
) -> dict:
    """INSERT a new document row and return it as a dict.

    Raises psycopg.errors.UniqueViolation if (kb_id, source_uri) already exists.
    """
    returning = ", ".join(_DOC_COLS)
    with get_pool().connection() as conn:
        row = conn.execute(
            f"INSERT INTO documents "
            f"(kb_id, source_uri, source, source_type, status, "
            f"storage_key, content_version, connector_id, file_size, doc_type) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {returning}",
            [kb_id, source_uri, source, source_type, status,
             storage_key, content_version, connector_id, file_size, doc_type],
        ).fetchone()
        conn.commit()
    return _row_to_doc(row)


def get_doc_by_id(doc_id: str) -> dict | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            _DOC_SELECT + " WHERE doc_id = %s",
            [doc_id],
        ).fetchone()
    return _row_to_doc(row) if row else None


def get_doc_by_source_uri(kb_id: str, source_uri: str) -> dict | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            _DOC_SELECT + " WHERE kb_id = %s AND source_uri = %s",
            [kb_id, source_uri],
        ).fetchone()
    return _row_to_doc(row) if row else None


def update_doc_fields(doc_id: str, fields: dict[str, Any]) -> None:
    """UPDATE arbitrary document fields by doc_id. Always sets updated_at = NOW()."""
    safe = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATE_FIELDS}
    if not safe:
        return
    set_parts = [f"{k} = %s" for k in safe]
    set_parts.append("updated_at = NOW()")
    with get_pool().connection() as conn:
        conn.execute(
            f"UPDATE documents SET {', '.join(set_parts)} WHERE doc_id = %s",
            list(safe.values()) + [doc_id],
        )
        conn.commit()


def soft_delete_doc(doc_id: str) -> None:
    """Set status=deleted and deleted_at=NOW(). Row is retained; Qdrant chunks must be removed separately."""
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE documents SET status = 'deleted', deleted_at = NOW(), updated_at = NOW() WHERE doc_id = %s",
            [doc_id],
        )
        conn.commit()
    logger.info("Doc soft-deleted: doc_id=%s", doc_id)


def list_docs(
    kb_id: str,
    *,
    include_deleted: bool = False,
    status_filter: str | None = None,
) -> list[dict]:
    conditions = ["kb_id = %s"]
    params: list[Any] = [kb_id]

    if not include_deleted:
        conditions.append("status != 'deleted'")
    if status_filter is not None:
        conditions.append("status = %s")
        params.append(status_filter)

    where = " AND ".join(conditions)
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"{_DOC_SELECT} WHERE {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [_row_to_doc(r) for r in rows]


def list_docs_paginated(
    kb_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    include_deleted: bool = False,
) -> tuple[list[dict], int]:
    """Paginated, filtered, and sorted document list for a KB.

    Returns (items, total) where total is the count after filtering.
    page is 1-based; out-of-range page returns ([], total).
    sort_by must be one of _ALLOWED_SORT_FIELDS (caller must validate).
    NULL values for chunk_count / file_size sort last regardless of direction.
    """
    conditions = ["kb_id = %s"]
    params: list[Any] = [kb_id]

    if not include_deleted:
        conditions.append("status != 'deleted'")
    if status:
        conditions.append("status = %s")
        params.append(status)
    if search:
        conditions.append("source ILIKE %s")
        params.append(f"%{search}%")

    where = " AND ".join(conditions)
    order_dir = "DESC" if sort_order == "desc" else "ASC"
    nulls_clause = "NULLS LAST" if sort_by in _NULL_LAST_FIELDS else ""
    order_clause = f"{sort_by} {order_dir} {nulls_clause}".strip()

    offset = (page - 1) * page_size
    with get_pool().connection() as conn:
        total: int = conn.execute(
            f"SELECT COUNT(*) FROM documents WHERE {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"{_DOC_SELECT} WHERE {where} ORDER BY {order_clause} LIMIT %s OFFSET %s",
            params + [page_size, offset],
        ).fetchall()

    return [_row_to_doc(r) for r in rows], total
