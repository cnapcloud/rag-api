"""Redis client factory — ingest/delete queue only.

KB and document metadata have been moved to Postgres (infra/postgres.py).
Redis is used exclusively for the ingest and delete event queues.
"""

from __future__ import annotations

import logging

import redis as redis_lib

from rag_api.config.settings import get_settings

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
            socket_connect_timeout=cfg.timeout_seconds,
            socket_timeout=cfg.timeout_seconds,
        )
    return _client


def ping() -> bool:
    try:
        get_redis_client().ping()
        return True
    except Exception as e:
        logger.warning("Redis ping failed: %s", e)
        return False
