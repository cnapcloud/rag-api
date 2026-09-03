"""GET /health, GET /ready."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_PING_CHECKS = ("qdrant", "redis", "postgres")
_NON_CRITICAL_CHECKS = ("s3",)  # ingest-only deps; failure is reported but doesn't flip overall status

# Default OpenAI-compatible /v1 base per provider when provider.url is empty.
_PROVIDER_V1_DEFAULTS = {
    "openai": "https://api.openai.com/v1",
    "jina": "https://api.jina.ai/v1",
}


@router.get("/health")
async def liveness():
    return {"status": "ok"}


async def _ping_ok(name: str, fn: Callable[[], bool]) -> bool:
    # ping() implementations are synchronous (qdrant-client/redis-py/psycopg are
    # all blocking) - run off the event loop so concurrent /ready calls don't
    # serialize on it (uvicorn runs a single worker, no other request can
    # progress while a blocking call holds the loop).
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=5)
    except TimeoutError:
        logger.error("Readiness check timed out: %s", name)
        return False


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


async def _provider_ok(label: str, v1_base: str, api_key: str | None) -> bool:
    """Reachability probe for an embedding backend via GET {v1_base}/models.

    Every provider we support exposes the OpenAI-compatible /v1/models endpoint -- native
    OpenAI, Jina, Ollama's compat layer, and self-hosted servers (vLLM, vllm-mlx, LM Studio,
    TEI). A transport error, 5xx, or 404 (endpoint not where provider.url points) means
    unreachable; 200 / 401 / 403 / 429 / other 4xx all mean the server answered.
    """
    url = v1_base.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(url, headers=headers)
        if r.status_code >= 500 or r.status_code == 404:
            logger.error("Readiness check failed: %s: HTTP %s", label, r.status_code)
            return False
        return True
    except Exception as e:
        logger.error("Readiness check failed: %s: %s", label, e)
        return False


@router.get("/ready")
async def readiness():
    from rag_api.config.settings import get_settings, resolve_provider_conn
    from rag_api.infra.postgres import ping as postgres_ping
    from rag_api.infra.qdrant import ping as qdrant_ping
    from rag_api.infra.redis import ping as redis_ping

    cfg = get_settings()
    provider = cfg.provider
    provider_name = (provider.name or "").strip() or "ollama"
    conn = resolve_provider_conn(provider)

    checks: dict[str, bool] = {
        "qdrant": await _ping_ok("qdrant", qdrant_ping),
        "redis": await _ping_ok("redis", redis_ping),
        "postgres": await _ping_ok("postgres", postgres_ping),
        "s3": await _s3_ok(),
    }

    # Embedding provider probe (GET {v1_base}/models), keyed by the configured provider name so
    # rag-admin can label the tile. ollama's provider.url is a bare host (US-50 convention) so
    # its /v1 compat layer is appended; openai/jina fall back to their SaaS base; an unknown
    # name uses provider.url as-is (already /v1 by convention). An unknown name with no url is a
    # misconfiguration (build_embed_model would reject it) -- left unprobed.
    if provider_name == "ollama":
        checks[provider_name] = await _provider_ok(
            provider_name, f"{conn.base_url.rstrip('/')}/v1", None
        )
    elif provider_name in _PROVIDER_V1_DEFAULTS:
        checks[provider_name] = await _provider_ok(
            provider_name, conn.base_url or _PROVIDER_V1_DEFAULTS[provider_name], conn.api_key
        )
    elif conn.base_url:
        checks[provider_name] = await _provider_ok(provider_name, conn.base_url, conn.api_key)

    for infra in _PING_CHECKS:
        if not checks[infra]:
            logger.error("Readiness check failed: %s", infra)

    critical_ok = all(v for k, v in checks.items() if k not in _NON_CRITICAL_CHECKS)
    return JSONResponse(
        status_code=200 if critical_ok else 503,
        content={
            "status": "ready" if critical_ok else "not_ready",
            "provider": provider_name,
            "checks": checks,
        },
    )
