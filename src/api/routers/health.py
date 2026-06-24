"""GET /health, GET /ready."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_PING_CHECKS = ("qdrant", "redis", "postgres")


@router.get("/health")
async def liveness():
    return {"status": "ok"}


async def _s3_ok() -> bool:
    from infra.s3 import get_s3_client

    try:
        get_s3_client().list_buckets()
        return True
    except Exception as e:
        logger.error("Readiness check failed: s3: %s", e)
        return False


async def _ollama_ok(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{url}/api/tags")
        if r.status_code != 200:
            logger.error("Readiness check failed: ollama: HTTP %s", r.status_code)
            return False
        return True
    except Exception as e:
        logger.error("Readiness check failed: ollama: %s", e)
        return False


async def _openai_ok(api_key: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if r.status_code != 200:
            logger.error("Readiness check failed: openai: HTTP %s", r.status_code)
            return False
        return True
    except Exception as e:
        logger.error("Readiness check failed: openai: %s", e)
        return False


@router.get("/ready")
async def readiness():
    from config.settings import get_settings
    from infra.postgres import ping as postgres_ping
    from infra.qdrant import ping as qdrant_ping
    from infra.redis import ping as redis_ping

    cfg = get_settings()
    emb = cfg.embedding

    checks: dict[str, bool] = {
        "qdrant": qdrant_ping(),
        "redis": redis_ping(),
        "postgres": postgres_ping(),
        "s3": await _s3_ok(),
    }

    if emb.provider == "ollama":
        checks["ollama"] = await _ollama_ok(emb.ollama_url)
    elif emb.provider == "openai":
        checks["openai"] = await _openai_ok(emb.openai_api_key)

    for name in _PING_CHECKS:
        if not checks[name]:
            logger.error("Readiness check failed: %s", name)

    all_ok = all(checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
    )
