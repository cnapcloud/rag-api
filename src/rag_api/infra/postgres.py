"""Postgres connection pool, schema migrations, KB and document metadata CRUD."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psycopg_pool
from psycopg.types.json import Jsonb

from rag_api.config.settings import get_settings
from rag_api.exceptions import ConfigError

if TYPE_CHECKING:
    from rag_api.pipeline.steps.chunk import ParentChunk

logger = logging.getLogger(__name__)

_pool: psycopg_pool.ConnectionPool | None = None


def generate_id() -> str:
    """Generate a 16-char hex ID (64-bit, URL-safe)."""
    return uuid.uuid4().hex[:16]


def _to_local_iso(dt: datetime | None) -> str:
    """Convert a UTC-aware datetime to the server's local timezone ISO string."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone().isoformat()


# Fields allowed in update_doc_fields() to prevent SQL injection via dict keys.
_ALLOWED_UPDATE_FIELDS = frozenset({
    "title", "source", "storage_key", "content_version", "connector_id", "status",
    "deleted_at", "run_id", "last_error", "process_started_at", "process_finished_at",
    "chunk_count", "file_size", "doc_type", "embedding_model", "chunk_strategy", "doc_created_at",
    "title_hash", "content_simhash", "duplicate_of",
})

_ALLOWED_SORT_FIELDS = frozenset({"updated_at", "created_at", "title", "chunk_count", "file_size"})
_NULL_LAST_FIELDS = frozenset({"chunk_count", "file_size"})

# Column order for all documents SELECT queries — must match CREATE TABLE order.
_DOC_COLS = (
    "doc_id", "kb_id", "title", "source_type", "source", "storage_key",
    "content_version", "connector_id", "status", "deleted_at", "run_id", "last_error",
    "created_at", "updated_at", "process_started_at", "process_finished_at",
    "chunk_count", "file_size", "doc_type", "embedding_model", "chunk_strategy", "doc_created_at",
    "title_hash", "content_simhash", "duplicate_of",
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
        pool = psycopg_pool.ConnectionPool(conninfo, min_size=1, max_size=cfg.pool_size, open=False)
        pool.open(wait=True, timeout=cfg.connect_timeout)
        _pool = pool
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
    migration_dir = Path(__file__).parents[3] / "migrations"
    if not migration_dir.is_dir():
        # A missing dir silently glob()s to zero files (no error), which used to let the
        # base schema go uncreated with no signal -- e.g. a downstream image (rag-ent-api)
        # copying src/ from this repo without also copying the sibling migrations/ dir.
        raise ConfigError(f"Migrations directory not found: {migration_dir}")

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


_ALLOWED_KB_SORT_FIELDS = frozenset({"kb_id", "kb_name", "status", "created_at", "updated_at"})


def list_kbs(sort_by: str = "kb_id", sort_order: str = "asc") -> list[dict]:
    col = sort_by if sort_by in _ALLOWED_KB_SORT_FIELDS else "kb_id"
    direction = "ASC" if sort_order.lower() == "asc" else "DESC"
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT kb_id, kb_name, description, tags, status, created_at, updated_at "
            f"FROM knowledge_bases ORDER BY {col} {direction}",
        ).fetchall()
    return [
        {
            "kb_id": r[0],
            "kb_name": r[1],
            "description": r[2],
            "tags": list(r[3]) if r[3] else [],
            "status": r[4],
            "created_at": _to_local_iso(r[5]),
            "updated_at": _to_local_iso(r[6]),
        }
        for r in rows
    ]


def update_kb_meta(
    kb_id: str,
    kb_name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> None:
    parts: list[str] = []
    params: list[Any] = []
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
# KB settings overrides — docs/internal/design/kb-settings-override.md
# ──────────────────────────────────────────────

def get_kb_settings_overrides(kb_id: str) -> dict[str, Any]:
    """Return all override rows for a KB as a flat dot-key dict. Empty dict if none stored."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM kb_settings_overrides WHERE kb_id = %s",
            [kb_id],
        ).fetchall()
    return {key: value for key, value in rows}


def upsert_kb_settings_override(kb_id: str, key: str, value: Any) -> None:
    """Insert or update a single override key. Independent row write — safe under concurrent
    PATCH requests touching different keys (no read-modify-write on a shared blob)."""
    with get_pool().connection() as conn:
        conn.execute(
            "INSERT INTO kb_settings_overrides (kb_id, key, value) VALUES (%s, %s, %s) "
            "ON CONFLICT (kb_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
            [kb_id, key, Jsonb(value)],
        )
        conn.commit()


def delete_kb_settings_override(kb_id: str, key: str) -> None:
    """Remove a single override key. No-op if it doesn't exist."""
    with get_pool().connection() as conn:
        conn.execute(
            "DELETE FROM kb_settings_overrides WHERE kb_id = %s AND key = %s",
            [kb_id, key],
        )
        conn.commit()


def replace_kb_settings_overrides(kb_id: str, overrides: dict[str, Any]) -> None:
    """Replace all override rows for a KB in one transaction (PUT semantics)."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM kb_settings_overrides WHERE kb_id = %s", [kb_id])
        if overrides:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO kb_settings_overrides (kb_id, key, value) VALUES (%s, %s, %s)",
                    [(kb_id, key, Jsonb(value)) for key, value in overrides.items()],
                )
        conn.commit()


def clear_kb_settings_overrides(kb_id: str) -> None:
    """Delete every override row for a KB (full reset to global settings)."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM kb_settings_overrides WHERE kb_id = %s", [kb_id])
        conn.commit()


# ──────────────────────────────────────────────
# Document metadata
# ──────────────────────────────────────────────

def _row_to_doc(row: tuple) -> dict:
    d = dict(zip(_DOC_COLS, row))
    for col in _DATETIME_COLS:
        if d[col] is not None:
            d[col] = _to_local_iso(d[col])
    return d


def create_doc(
    kb_id: str,
    source: str,
    title: str,
    source_type: str,
    *,
    status: str = "pending",
    storage_key: str | None = None,
    content_version: str | None = None,
    connector_id: str | None = None,
    file_size: int | None = None,
    doc_type: str | None = None,
    doc_created_at: datetime | None = None,
) -> dict:
    """INSERT a new document row and return it as a dict.

    doc_id is app-generated as a 16-char hex ID.
    Raises psycopg.errors.UniqueViolation if (kb_id, source) already exists.
    """
    doc_id = generate_id()
    returning = ", ".join(_DOC_COLS)
    with get_pool().connection() as conn:
        row = conn.execute(
            f"INSERT INTO documents "
            f"(doc_id, kb_id, source, title, source_type, status, "
            f"storage_key, content_version, connector_id, file_size, doc_type, doc_created_at) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {returning}",
            [doc_id, kb_id, source, title, source_type, status,
             storage_key, content_version, connector_id, file_size, doc_type, doc_created_at],
        ).fetchone()
        conn.commit()
    assert row is not None, "INSERT ... RETURNING always yields exactly one row on success"
    return _row_to_doc(row)


def get_pending_doc_count_for_connector(connector_id: str) -> int:
    """Count docs owned by connector_id that have not yet reached a terminal status."""
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM documents "
            "WHERE connector_id = %s AND status NOT IN ('indexed', 'failed', 'deleted', 'deleting', 'outdated')",
            [connector_id],
        ).fetchone()
    return int(row[0]) if row else 0


def get_active_ingest_docs_for_connector(connector_id: str) -> list[dict]:
    """Return docs owned by connector_id with status 'pending' or 'running'."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            _DOC_SELECT + " WHERE connector_id = %s AND status IN ('pending', 'running')",
            [connector_id],
        ).fetchall()
    return [_row_to_doc(r) for r in rows]


def get_active_ingest_docs_for_kb(kb_id: str) -> list[dict]:
    """Return docs in kb_id with status 'pending' or 'running', regardless of connector."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            _DOC_SELECT + " WHERE kb_id = %s AND status IN ('pending', 'running')",
            [kb_id],
        ).fetchall()
    return [_row_to_doc(r) for r in rows]


def get_existing_doc_ids(doc_ids: list[str]) -> set[str]:
    """Return the subset of doc_ids that still have a row (any status)."""
    if not doc_ids:
        return set()
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT doc_id FROM documents WHERE doc_id = ANY(%s)",
            [doc_ids],
        ).fetchall()
    return {r[0] for r in rows}


def get_doc_by_id(doc_id: str) -> dict | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            _DOC_SELECT + " WHERE doc_id = %s",
            [doc_id],
        ).fetchone()
    return _row_to_doc(row) if row else None


def get_doc_by_source(kb_id: str, source: str) -> dict | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            _DOC_SELECT + " WHERE kb_id = %s AND source = %s",
            [kb_id, source],
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


def hard_delete_doc(doc_id: str) -> None:
    """Physically delete the document row. Cascades to simhash_bands and minhash_bands."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM documents WHERE doc_id = %s", [doc_id])
        conn.commit()
    logger.info("Doc hard-deleted: doc_id=%s", doc_id)


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
    source_type: str | None = None,
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
    if source_type:
        conditions.append("source_type = %s")
        params.append(source_type)
    if search:
        conditions.append("(title ILIKE %s OR source ILIKE %s OR doc_id ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    order_dir = "DESC" if sort_order == "desc" else "ASC"
    nulls_clause = "NULLS LAST" if sort_by in _NULL_LAST_FIELDS else ""
    order_clause = f"{sort_by} {order_dir} {nulls_clause}".strip()

    offset = (page - 1) * page_size
    with get_pool().connection() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM documents WHERE {where}", params
        ).fetchone()
        total = int(count_row[0]) if count_row else 0
        rows = conn.execute(
            f"{_DOC_SELECT} WHERE {where} ORDER BY {order_clause} LIMIT %s OFFSET %s",
            params + [page_size, offset],
        ).fetchall()

    return [_row_to_doc(r) for r in rows], total


def list_all_docs_paginated(
    page: int,
    page_size: int,
    status: str | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    include_deleted: bool = False,
) -> tuple[list[dict], int]:
    """Paginated, filtered, and sorted document list across all KBs."""
    conditions: list[str] = []
    params: list[Any] = []

    if not include_deleted:
        conditions.append("status != 'deleted'")
    if status:
        conditions.append("status = %s")
        params.append(status)
    if search:
        conditions.append("(title ILIKE %s OR source ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    order_dir = "DESC" if sort_order == "desc" else "ASC"
    nulls_clause = "NULLS LAST" if sort_by in _NULL_LAST_FIELDS else ""
    order_clause = f"{sort_by} {order_dir} {nulls_clause}".strip()

    offset = (page - 1) * page_size
    with get_pool().connection() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM documents {where}", params
        ).fetchone()
        total = int(count_row[0]) if count_row else 0
        rows = conn.execute(
            f"{_DOC_SELECT} {where} ORDER BY {order_clause} LIMIT %s OFFSET %s",
            params + [page_size, offset],
        ).fetchall()

    return [_row_to_doc(r) for r in rows], total


def list_docs_by_connector(
    connector_id: str,
    *,
    include_deleted: bool = False,
) -> list[dict]:
    conditions = ["connector_id = %s"]
    params: list[Any] = [connector_id]
    if not include_deleted:
        conditions.append("status != 'deleted'")
    where = " AND ".join(conditions)
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"{_DOC_SELECT} WHERE {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [_row_to_doc(r) for r in rows]


def list_docs_by_connector_paginated(
    connector_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    include_deleted: bool = False,
) -> tuple[list[dict], int]:
    conditions = ["connector_id = %s"]
    params: list[Any] = [connector_id]

    if not include_deleted:
        conditions.append("status != 'deleted'")
    if status:
        conditions.append("status = %s")
        params.append(status)
    if search:
        conditions.append("(title ILIKE %s OR source ILIKE %s OR doc_id ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    order_dir = "DESC" if sort_order == "desc" else "ASC"
    nulls_clause = "NULLS LAST" if sort_by in _NULL_LAST_FIELDS else ""
    order_clause = f"{sort_by} {order_dir} {nulls_clause}".strip()

    offset = (page - 1) * page_size
    with get_pool().connection() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM documents WHERE {where}", params
        ).fetchone()
        total = int(count_row[0]) if count_row else 0
        rows = conn.execute(
            f"{_DOC_SELECT} WHERE {where} ORDER BY {order_clause} LIMIT %s OFFSET %s",
            params + [page_size, offset],
        ).fetchall()

    return [_row_to_doc(r) for r in rows], total


# ──────────────────────────────────────────────
# Connector metadata
# ──────────────────────────────────────────────

_CONNECTOR_COLS = (
    "connector_id", "kb_id", "name", "source_type", "config",
    "sync_schedule", "schedule_enabled", "sync_status", "sync_started_at",
    "last_synced_at", "status", "last_error", "created_at", "updated_at",
)
_CONNECTOR_SELECT = "SELECT " + ", ".join(_CONNECTOR_COLS) + " FROM connectors"
_CONNECTOR_DATETIME_COLS = frozenset({"sync_started_at", "last_synced_at", "created_at", "updated_at"})
_ALLOWED_CONNECTOR_UPDATE_FIELDS = frozenset({"name", "config", "sync_schedule", "schedule_enabled", "status"})
_ALLOWED_CONNECTOR_SORT_FIELDS = frozenset({"name", "connector_id", "kb_id", "source_type", "status", "last_synced_at", "created_at", "updated_at"})
_CONNECTOR_NULL_LAST_FIELDS = frozenset({"last_synced_at"})


def _row_to_connector(row: tuple) -> dict:
    d = dict(zip(_CONNECTOR_COLS, row))
    for col in _CONNECTOR_DATETIME_COLS:
        if d[col] is not None:
            d[col] = _to_local_iso(d[col])
    return d


def create_connector(
    kb_id: str,
    name: str,
    source_type: str,
    config: dict,
    sync_schedule: str | None = None,
    schedule_enabled: bool = False,
) -> dict:
    """INSERT a new connector row and return it as a dict.

    connector_id is app-generated as a 16-char hex ID.
    """
    connector_id = generate_id()
    returning = ", ".join(_CONNECTOR_COLS)
    with get_pool().connection() as conn:
        row = conn.execute(
            f"INSERT INTO connectors "
            f"(connector_id, kb_id, name, source_type, config, sync_schedule, schedule_enabled) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {returning}",
            [connector_id, kb_id, name, source_type, Jsonb(config), sync_schedule, schedule_enabled],
        ).fetchone()
        conn.commit()
    assert row is not None, "INSERT ... RETURNING always yields exactly one row on success"
    return _row_to_connector(row)


def get_connector(connector_id: str) -> dict | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            _CONNECTOR_SELECT + " WHERE connector_id = %s",
            [connector_id],
        ).fetchone()
    return _row_to_connector(row) if row else None


def list_connectors(
    kb_id: str | list[str] | None = None,
    source_type: str | None = None,
    status: str | None = None,
    has_schedule: bool | None = None,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
) -> list[dict]:
    if isinstance(kb_id, list) and not kb_id:
        return []

    conditions: list[str] = []
    params: list[Any] = []
    if isinstance(kb_id, list):
        placeholders = ", ".join(["%s"] * len(kb_id))
        conditions.append(f"kb_id IN ({placeholders})")
        params.extend(kb_id)
    elif kb_id is not None:
        conditions.append("kb_id = %s")
        params.append(kb_id)
    if source_type is not None:
        conditions.append("source_type = %s")
        params.append(source_type)
    if status is not None:
        conditions.append("status = %s")
        params.append(status)
    if has_schedule is True:
        conditions.append("sync_schedule IS NOT NULL")
    elif has_schedule is False:
        conditions.append("sync_schedule IS NULL")
    if search is not None:
        conditions.append("(LOWER(name) LIKE %s OR LOWER(connector_id) LIKE %s)")
        params.extend([f"%{search.lower()}%", f"%{search.lower()}%"])

    col = sort_by if sort_by in _ALLOWED_CONNECTOR_SORT_FIELDS else "created_at"
    direction = "ASC" if sort_order.lower() == "asc" else "DESC"
    null_order = "NULLS LAST" if col in _CONNECTOR_NULL_LAST_FIELDS else ""
    order_clause = f"ORDER BY {col} {direction} {null_order}".strip()

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"{_CONNECTOR_SELECT} {where} {order_clause}",
            params,
        ).fetchall()
    return [_row_to_connector(r) for r in rows]


def update_connector(connector_id: str, fields: dict) -> dict | None:
    """UPDATE allowed connector fields. Returns updated row or None if not found."""
    safe = {k: v for k, v in fields.items() if k in _ALLOWED_CONNECTOR_UPDATE_FIELDS}
    if not safe:
        return get_connector(connector_id)

    set_parts: list[str] = []
    params: list[Any] = []
    for k, v in safe.items():
        set_parts.append(f"{k} = %s")
        params.append(Jsonb(v) if k == "config" and v is not None else v)
    if "status" in safe:
        set_parts.append("last_error = NULL")
    set_parts.append("updated_at = NOW()")
    params.append(connector_id)

    returning = ", ".join(_CONNECTOR_COLS)
    with get_pool().connection() as conn:
        row = conn.execute(
            f"UPDATE connectors SET {', '.join(set_parts)} WHERE connector_id = %s RETURNING {returning}",
            params,
        ).fetchone()
        conn.commit()
    return _row_to_connector(row) if row else None


def delete_connector(connector_id: str) -> None:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM connectors WHERE connector_id = %s", [connector_id])
        conn.commit()
    logger.info("Connector deleted: connector_id=%s", connector_id)


def set_connector_sync_status(
    connector_id: str,
    sync_status: str,
    last_synced_at: datetime | None = None,
    last_error: str | None = None,
) -> None:
    """Update sync_status and manage sync_started_at lifecycle.

    running -> sets sync_started_at = NOW()
    idle    -> clears sync_started_at = NULL; optionally sets last_synced_at
    last_error, when given, records a sync-outcome note without touching status
    (used when a pipeline hook stops the sync cleanly).
    """
    parts = ["sync_status = %s", "updated_at = NOW()"]
    params: list[Any] = [sync_status]

    if sync_status == "running":
        parts.append("sync_started_at = NOW()")
    else:
        parts.append("sync_started_at = NULL")

    if last_synced_at is not None:
        parts.append("last_synced_at = %s")
        params.append(last_synced_at)

    if last_error is not None:
        parts.append("last_error = %s")
        params.append(last_error[:500])

    params.append(connector_id)
    with get_pool().connection() as conn:
        conn.execute(
            f"UPDATE connectors SET {', '.join(parts)} WHERE connector_id = %s",
            params,
        )
        conn.commit()


def set_connector_status(connector_id: str, status: str, error: str | None = None) -> None:
    """Set connector status. When status='error', stores the error message in last_error;
    for any other status, last_error is cleared.
    """
    with get_pool().connection() as conn:
        if status == "error":
            conn.execute(
                "UPDATE connectors SET status = %s, last_error = %s, updated_at = NOW() "
                "WHERE connector_id = %s",
                [status, (error or "")[:500], connector_id],
            )
        else:
            conn.execute(
                "UPDATE connectors SET status = %s, last_error = NULL, updated_at = NOW() "
                "WHERE connector_id = %s",
                [status, connector_id],
            )
        conn.commit()


def get_connector_doc_counts(connector_id: str) -> dict[str, int]:
    """Return {status: count, ..., "total": n} for documents owned by this connector."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM documents WHERE connector_id = %s GROUP BY status",
            [connector_id],
        ).fetchall()
    counts: dict[str, int] = {"indexed": 0, "pending": 0, "running": 0, "failed": 0, "deleted": 0, "outdated": 0}
    for status, n in rows:
        counts[status] = int(n)
    counts["total"] = sum(v for k, v in counts.items() if k != "total")
    return counts


def get_kb_doc_counts(kb_id: str) -> dict[str, int]:
    """Return {status: count, ..., "total": n} for all documents in a KB."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) FROM documents WHERE kb_id = %s GROUP BY status",
            [kb_id],
        ).fetchall()
    counts: dict[str, int] = {"indexed": 0, "pending": 0, "running": 0, "failed": 0, "deleted": 0, "outdated": 0}
    for status, n in rows:
        counts[status] = int(n)
    counts["total"] = sum(v for k, v in counts.items() if k != "total")
    return counts


def save_simhash_bands(doc_id: str, bands: list[tuple[int, str]]) -> None:
    """Store SimHash band entries for a document.

    Looks up kb_id from the documents table. Upserts to tolerate re-ingest.
    bands: list of (band_index, band_value_hex) as returned by get_bands().
    """
    with get_pool().connection() as conn:
        row = conn.execute("SELECT kb_id FROM documents WHERE doc_id = %s", [doc_id]).fetchone()
        if row is None:
            raise ValueError(f"Document not found for simhash save: doc_id={doc_id}")
        kb_id = row[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO simhash_bands (band_id, doc_id, kb_id, band_index, band_value)"
                " VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (band_id) DO UPDATE SET band_value = EXCLUDED.band_value",
                [(f"{doc_id}:{idx}", doc_id, kb_id, idx, int(val, 16)) for idx, val in bands],
            )
        conn.commit()
    logger.info("SimHash bands saved: doc_id=%s num_bands=%d", doc_id, len(bands))


def find_simhash_candidates(bands: list[tuple[int, str]], kb_id: str) -> set[str]:
    """Return doc_ids that share at least one (band_index, band_value) pair within the same KB.

    bands: list of (band_index, band_value_hex) as returned by get_bands().
    """
    clauses = ["(sb.band_index = %s AND sb.band_value = %s)"] * len(bands)
    params: list[Any] = [kb_id]
    for idx, val in bands:
        params.extend([idx, int(val, 16)])
    sql = (
        f"SELECT DISTINCT sb.doc_id FROM simhash_bands sb"
        f" JOIN documents d ON d.doc_id = sb.doc_id"
        f" WHERE sb.kb_id = %s AND d.status = 'indexed' AND ({' OR '.join(clauses)})"
    )
    with get_pool().connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {row[0] for row in rows}


def get_docs_fingerprints(doc_ids: list[str]) -> dict[str, dict]:
    """Return {doc_id: {content_simhash, title_hash}} for the given doc_ids.

    Used by SimHash detection to retrieve candidate fingerprints in one query.
    content_simhash is a signed BIGINT (i64); caller converts to u64 for Hamming.
    """
    if not doc_ids:
        return {}
    placeholders = ",".join(["%s"] * len(doc_ids))
    with get_pool().connection() as conn:
        rows = conn.execute(
            f"SELECT doc_id, content_simhash, title_hash FROM documents"
            f" WHERE doc_id IN ({placeholders})",
            doc_ids,
        ).fetchall()
    return {row[0]: {"content_simhash": row[1], "title_hash": row[2]} for row in rows}


def delete_simhash_bands(doc_id: str) -> None:
    """Remove all simhash band entries for a document."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM simhash_bands WHERE doc_id = %s", [doc_id])
        conn.commit()
    logger.info("SimHash bands deleted: doc_id=%s", doc_id)


# ──────────────────────────────────────────────
# MinHash band CRUD (stage 2 dedup)
# ──────────────────────────────────────────────

def save_minhash_bands(doc_id: str, signature: list[int]) -> None:
    """Store a 128-element MinHash signature as individual rows in minhash_bands.

    Each row: (doc_id, kb_id, band_index=0..127, band_hash=MinHash value at that position).
    Looks up kb_id from the documents table. Upserts to tolerate re-ingest.
    """
    with get_pool().connection() as conn:
        row = conn.execute("SELECT kb_id FROM documents WHERE doc_id = %s", [doc_id]).fetchone()
        if row is None:
            raise ValueError(f"Document not found for minhash save: doc_id={doc_id}")
        kb_id = row[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO minhash_bands (doc_id, kb_id, band_index, band_hash) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (doc_id, band_index) DO UPDATE SET band_hash = EXCLUDED.band_hash",
                [(doc_id, kb_id, i, h) for i, h in enumerate(signature)],
            )
        conn.commit()
    logger.info("MinHash bands saved: doc_id=%s num_values=%d", doc_id, len(signature))


def get_minhash_signature(doc_id: str) -> list[int] | None:
    """Return the stored MinHash signature (ordered by band_index), or None if absent."""
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT band_hash FROM minhash_bands WHERE doc_id = %s ORDER BY band_index",
            [doc_id],
        ).fetchall()
    if not rows:
        return None
    return [row[0] for row in rows]


def find_minhash_candidates(signature: list[int], kb_id: str, num_bands: int = 16) -> set[str]:
    """Return doc_ids that share ALL MinHash values in at least one band within the same KB.

    Uses LSH band approach: the signature is split into num_bands bands of equal size.
    A candidate doc matches a band if every position within that band has the same hash value.
    This is more selective than any-match, reducing false positives for large corpora.
    """
    n = len(signature)
    rows_per_band = n // num_bands

    union_parts: list[str] = []
    all_params: list[Any] = []

    for band_idx in range(num_bands):
        start = band_idx * rows_per_band
        or_clauses = []
        for row in range(rows_per_band):
            pos = start + row
            or_clauses.append("(mb.band_index = %s AND mb.band_hash = %s)")
            all_params.extend([pos, signature[pos]])

        all_params.append(kb_id)
        union_parts.append(
            f"SELECT doc_id FROM ("
            f"SELECT mb.doc_id, COUNT(*) AS cnt FROM minhash_bands mb"
            f" JOIN documents d ON d.doc_id = mb.doc_id"
            f" WHERE ({' OR '.join(or_clauses)}) AND mb.kb_id = %s AND d.status = 'indexed'"
            f" GROUP BY mb.doc_id"
            f") s{band_idx} WHERE cnt = {rows_per_band}"
        )

    sql = " UNION ".join(union_parts)
    with get_pool().connection() as conn:
        rows = conn.execute(sql, all_params).fetchall()
    return {row[0] for row in rows}


def find_title_candidates(title: str, threshold: float, kb_id: str) -> dict[str, float]:
    """Return {doc_id: similarity_score} for documents whose source matches title via pg_trgm.

    Uses GIN index idx_documents_source_trgm. Scoped to kb_id. Excludes deleted documents.
    """
    with get_pool().connection() as conn:
        # SET does not support parameter binding; threshold is a config float (not user input).
        conn.execute(f"SET LOCAL pg_trgm.similarity_threshold = {float(threshold)!r}")
        rows = conn.execute(
            "SELECT doc_id, similarity(title, %s) AS sim FROM documents"
            " WHERE kb_id = %s AND title %% %s AND status = 'indexed'",
            [title, kb_id, title],
        ).fetchall()
    return {row[0]: float(row[1]) for row in rows}


def delete_minhash_bands(doc_id: str) -> None:
    """Remove all MinHash band entries for a document."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM minhash_bands WHERE doc_id = %s", [doc_id])
        conn.commit()
    logger.info("MinHash bands deleted: doc_id=%s", doc_id)


# ──────────────────────────────────────────────
# Parent-child chunking ancestor storage — docs/internal/design/parent-child-chunking.md §4.1
# ──────────────────────────────────────────────

def save_parent_chunks(doc_id: str, kb_id: str, parents: list[ParentChunk]) -> None:
    """Insert ancestor rows for a document. No-op when parents is empty.

    Caller (pipeline/steps/upsert.py) must pass parents in root-first order (as returned by
    pipeline/steps/chunk.py's chunk()) — the self-referencing parent_id FK requires each row's
    parent to already exist. Upserts to tolerate re-ingest (chunk_id is deterministic —
    "{doc_id}:{idx}", see chunk.py _make_id_func).
    """
    if not parents:
        return
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO parent_chunks"
                " (chunk_id, doc_id, kb_id, level, parent_id, chunk_index, text, child_count,"
                "  page_num, page_label)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (chunk_id) DO UPDATE SET"
                "   level = EXCLUDED.level, parent_id = EXCLUDED.parent_id,"
                "   chunk_index = EXCLUDED.chunk_index, text = EXCLUDED.text,"
                "   child_count = EXCLUDED.child_count, page_num = EXCLUDED.page_num,"
                "   page_label = EXCLUDED.page_label",
                [
                    (
                        p.chunk_id, doc_id, kb_id, p.level, p.parent_id, p.chunk_index, p.text,
                        p.child_count, p.page_num, p.page_label,
                    )
                    for p in parents
                ],
            )
        conn.commit()
    logger.info("Parent chunks saved: doc_id=%s count=%d", doc_id, len(parents))


def get_parent_chunks(chunk_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch ancestor rows by chunk_id -> {chunk_id: row}. Used by query/retriever.py's
    auto-merge (missing IDs are simply absent from the result — self-healing, design §5.2)."""
    if not chunk_ids:
        return {}
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT chunk_id, doc_id, kb_id, level, parent_id, chunk_index, text, child_count,"
            " page_num, page_label FROM parent_chunks WHERE chunk_id = ANY(%s)",
            [chunk_ids],
        ).fetchall()
    return {
        row[0]: {
            "chunk_id": row[0], "doc_id": row[1], "kb_id": row[2], "level": row[3],
            "parent_id": row[4], "chunk_index": row[5], "text": row[6], "child_count": row[7],
            "page_num": row[8], "page_label": row[9],
        }
        for row in rows
    }


def delete_parent_chunks_by_doc(doc_id: str) -> None:
    """Remove all parent_chunks rows for a document (any level)."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM parent_chunks WHERE doc_id = %s", [doc_id])
        conn.commit()
    logger.info("Parent chunks deleted: doc_id=%s", doc_id)

