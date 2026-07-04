"""GET /health, GET /ready."""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_PING_CHECKS = ("qdrant", "redis", "postgres")
_NON_CRITICAL_CHECKS = ("s3",)  # ingest-only deps; failure is reported but doesn't flip overall status


@router.get("/health")
async def liveness():
    return {"status": "ok"}


async def _s3_ok() -> bool:
    from rag_api.infra.s3 import get_s3_client

    def _check() -> None:
        get_s3_client().list_buckets()

    try:
        await asyncio.wait_for(asyncio.to_thread(_check), timeout=5)
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
    from rag_api.config.settings import get_settings
    from rag_api.infra.postgres import ping as postgres_ping
    from rag_api.infra.qdrant import ping as qdrant_ping
    from rag_api.infra.redis import ping as redis_ping

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

    critical_ok = all(v for name, v in checks.items() if name not in _NON_CRITICAL_CHECKS)
    return JSONResponse(
        status_code=200 if critical_ok else 503,
        content={"status": "ready" if critical_ok else "not_ready", "checks": checks},
    )
