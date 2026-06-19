"""Postgres connection pool, schema migrations, KB and document metadata CRUD."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import psycopg_pool

from config.settings import get_settings

logger = logging.getLogger(__name__)

_pool: psycopg_pool.ConnectionPool | None = None

_ALLOWED_DOC_FIELDS = frozenset({
    "status", "etag", "run_id", "updated_at", "chunk_count",
    "file_size", "doc_type", "embedding_model", "error", "doc_created_at",
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
            "SELECT kb_id, kb_name, description, tags, status, created_at FROM knowledge_bases WHERE kb_id = %s",
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
        "created_at": row[5].isoformat() if row[5] else "",
    }


def list_kb_ids() -> list[str]:
    with get_pool().connection() as conn:
        rows = conn.execute("SELECT kb_id FROM knowledge_bases ORDER BY kb_id").fetchall()
    return [r[0] for r in rows]


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

def set_doc_status(kb_id: str, object_key: str, fields: dict) -> None:
    """UPSERT a document row; created_at is set on INSERT and never overwritten."""
    safe = {k: v for k, v in fields.items() if k in _ALLOWED_DOC_FIELDS}
    if not safe:
        return
    col_names = list(safe.keys())
    values = list(safe.values())
    col_list = ", ".join(col_names)
    placeholders = ", ".join(["%s"] * len(values))
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in col_names)
    sql = (
        f"INSERT INTO documents (kb_id, object_key, {col_list}) "
        f"VALUES (%s, %s, {placeholders}) "
        f"ON CONFLICT (kb_id, object_key) DO UPDATE SET {set_clause}"
    )
    with get_pool().connection() as conn:
        conn.execute(sql, [kb_id, object_key] + values)
        conn.commit()


def _row_to_doc(row: tuple) -> dict:
    """Convert a documents SELECT row to a dict matching the old Redis hash schema."""
    status, etag, run_id, created_at, updated_at, chunk_count, file_size, doc_type, embedding_model, error, doc_created_at = row
    return {
        "status": status or "",
        "etag": etag or "",
        "run_id": run_id or "",
        "created_at": created_at.isoformat() if created_at else "",
        "updated_at": updated_at.isoformat() if updated_at else "",
        "chunk_count": str(chunk_count) if chunk_count is not None else "",
        "file_size": str(file_size) if file_size is not None else "",
        "doc_type": doc_type or "",
        "embedding_model": embedding_model or "",
        "error": error or "",
        "doc_created_at": doc_created_at.isoformat() if doc_created_at else "",
    }


_DOC_SELECT = """
    SELECT status, etag, run_id, created_at, updated_at,
           chunk_count, file_size, doc_type, embedding_model, error, doc_created_at
    FROM documents
"""


def get_doc_status(kb_id: str, object_key: str) -> dict | None:
    with get_pool().connection() as conn:
        row = conn.execute(
            _DOC_SELECT + "WHERE kb_id = %s AND object_key = %s",
            [kb_id, object_key],
        ).fetchone()
    return _row_to_doc(row) if row else None


def list_docs(kb_id: str) -> list[dict]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT object_key, status, etag, run_id, created_at, updated_at, "
            "chunk_count, file_size, doc_type, embedding_model, error, doc_created_at "
            "FROM documents WHERE kb_id = %s ORDER BY created_at",
            [kb_id],
        ).fetchall()
    result = []
    for row in rows:
        object_key = row[0]
        d = _row_to_doc(row[1:])
        d["object_key"] = object_key
        result.append(d)
    return result


def list_docs_by_status(kb_id: str, status: str) -> list[dict]:
    with get_pool().connection() as conn:
        rows = conn.execute(
            "SELECT object_key, status, etag, run_id, created_at, updated_at, "
            "chunk_count, file_size, doc_type, embedding_model, error, doc_created_at "
            "FROM documents WHERE kb_id = %s AND status = %s ORDER BY created_at",
            [kb_id, status],
        ).fetchall()
    result = []
    for row in rows:
        object_key = row[0]
        d = _row_to_doc(row[1:])
        d["object_key"] = object_key
        result.append(d)
    return result


def get_doc_etag(kb_id: str, object_key: str) -> str | None:
    """Return the stored ETag for a document regardless of its current status.

    set_processing() does not clear the etag column, so the previous ETag remains
    accessible even while status='running', enabling ETag-based dedup during re-uploads.
    """
    with get_pool().connection() as conn:
        row = conn.execute(
            "SELECT etag FROM documents WHERE kb_id = %s AND object_key = %s",
            [kb_id, object_key],
        ).fetchone()
    return row[0] if row and row[0] else None


def set_doc_etag(kb_id: str, object_key: str, etag: str) -> None:
    set_doc_status(kb_id, object_key, {"etag": etag, "updated_at": datetime.now(timezone.utc).isoformat()})


def delete_doc_etag(kb_id: str, object_key: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "UPDATE documents SET etag = NULL WHERE kb_id = %s AND object_key = %s",
            [kb_id, object_key],
        )
        conn.commit()


def delete_doc_meta(kb_id: str, object_key: str) -> None:
    with get_pool().connection() as conn:
        conn.execute(
            "DELETE FROM documents WHERE kb_id = %s AND object_key = %s",
            [kb_id, object_key],
        )
        conn.commit()
    logger.info("Doc meta deleted: kb=%s key=%s", kb_id, object_key)
