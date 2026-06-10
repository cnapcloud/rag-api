"""GET /health, GET /ready."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def liveness():
    return {"status": "ok"}


@router.get("/ready")
async def readiness():
    from config.settings import get_settings
    from infra.s3 import get_s3_client
    from infra.qdrant import ping as qdrant_ping
    from infra.redis import ping as redis_ping

    cfg = get_settings()
    checks: dict[str, bool] = {}

    # Qdrant
    checks["qdrant"] = qdrant_ping()

    # Redis
    checks["redis"] = redis_ping()

    # S3
    try:
        client = get_s3_client()
        client.list_buckets()
        checks["s3"] = True
    except Exception:
        checks["s3"] = False

    # Ollama (provider=ollama 인 경우만)
    if cfg.embedding.provider == "ollama":
        try:
            import httpx

            async with httpx.AsyncClient(timeout=3) as c:
                resp = await c.get(f"{cfg.embedding.ollama_url}/api/tags")
            checks["ollama"] = resp.status_code == 200
        except Exception:
            checks["ollama"] = False

    all_ok = all(checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ok else "not_ready",
            "checks": checks,
        },
    )