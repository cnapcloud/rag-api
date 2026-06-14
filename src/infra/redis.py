"""Redis client factory, ETag cache, and KB/document metadata CRUD."""

from __future__ import annotations

import logging

import redis as redis_lib

from config.settings import get_settings

logger = logging.getLogger(__name__)

_client: redis_lib.Redis | None = None


def get_redis_client() -> redis_lib.Redis:
    global _client
    if _client is None:
        cfg = get_settings().redis
        _client = redis_lib.Redis(
            host=cfg.host,
            port=cfg.port,
            password=cfg.password or None,
            db=cfg.db,
            decode_responses=True,
        )
    return _client


# ──────────────────────────────────────────────
# ETag cache
# ──────────────────────────────────────────────

def get_doc_etag(kb_id: str, object_key: str) -> str | None:
    """Return the stored ETag for a document, or None if absent."""
    return get_redis_client().get(f"etag:{kb_id}:{object_key}")  # type: ignore[return-value]


def set_doc_etag(kb_id: str, object_key: str, etag: str) -> None:
    get_redis_client().set(f"etag:{kb_id}:{object_key}", etag)


def delete_doc_etag(kb_id: str, object_key: str) -> None:
    get_redis_client().delete(f"etag:{kb_id}:{object_key}")


def delete_kb_etags(kb_id: str) -> int:
    """Delete all ETag keys for a KB and return the count deleted."""
    r = get_redis_client()
    keys = r.keys(f"etag:{kb_id}:*")
    return r.delete(*keys) if keys else 0


# ──────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────

def ping() -> bool:
    try:
        get_redis_client().ping()
        return True
    except Exception as e:
        logger.warning("Redis ping failed: %s", e)
        return False


# ──────────────────────────────────────────────
# KB metadata
# ──────────────────────────────────────────────

def kb_meta_key(kb_id: str) -> str:
    return f"kb:{kb_id}"


def register_kb(kb_id: str, description: str = "") -> None:
    from datetime import datetime, timezone

    r = get_redis_client()
    r.hset(kb_meta_key(kb_id), mapping={
        "description": description,
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    r.sadd("kbs", kb_id)
    logger.info("KB registered: %s", kb_id)


def list_kb_ids(client=None) -> list[str]:
    r = client or get_redis_client()
    return list(r.smembers("kbs"))


def delete_kb_meta(kb_id: str) -> None:
    r = get_redis_client()
    doc_keys = r.smembers(f"docs:{kb_id}")
    for doc_key in doc_keys:
        r.delete(f"doc:{kb_id}:{doc_key}")
    r.delete(f"docs:{kb_id}")
    r.delete(kb_meta_key(kb_id))
    r.srem("kbs", kb_id)
    delete_kb_etags(kb_id)
    logger.info("KB meta deleted: %s", kb_id)


# ──────────────────────────────────────────────
# Document metadata
# ──────────────────────────────────────────────

def set_doc_status(kb_id: str, object_key: str, fields: dict) -> None:
    from datetime import datetime, timezone

    r = get_redis_client()
    key = f"doc:{kb_id}:{object_key}"
    r.hset(key, mapping={k: str(v) for k, v in fields.items()})
    r.hsetnx(key, "created_at", datetime.now(timezone.utc).isoformat())
    r.sadd(f"docs:{kb_id}", object_key)


def get_doc_status(kb_id: str, object_key: str) -> dict | None:
    r = get_redis_client()
    data = r.hgetall(f"doc:{kb_id}:{object_key}")
    return data if data else None


def list_docs(kb_id: str, client=None) -> list[dict]:
    r = client or get_redis_client()
    keys = r.smembers(f"docs:{kb_id}")
    return [{"object_key": key, **r.hgetall(f"doc:{kb_id}:{key}")} for key in keys]


def list_docs_by_status(kb_id: str, status: str) -> list[dict]:
    return [d for d in list_docs(kb_id) if d.get("status") == status]


def delete_doc_meta(kb_id: str, object_key: str) -> None:
    r = get_redis_client()
    r.delete(f"doc:{kb_id}:{object_key}")
    r.srem(f"docs:{kb_id}", object_key)
    delete_doc_etag(kb_id, object_key)
    logger.info("Doc meta deleted: kb=%s key=%s", kb_id, object_key)
