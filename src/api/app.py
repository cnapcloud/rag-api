"""FastAPI app factory + startup events + global exception handlers."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis as redis_lib
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from botocore.exceptions import ClientError
from starlette.requests import Request

from api.routers import docs, health, internal, kb, search
from exceptions import ConfigError, ConflictError, IngestValidationError, NotFoundError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    mcp_sub_app = getattr(app.state, "mcp_sub_app", None)
    if mcp_sub_app is not None:
        async with mcp_sub_app.router.lifespan_context(mcp_sub_app):
            await _init_infrastructure()
            _start_queue_worker(app)
            yield
    else:
        await _init_infrastructure()
        _start_queue_worker(app)
        yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG API",
        description="LlamaIndex + Dagster 기반 RAG 파이프라인 API",
        version="0.1.0",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(kb.router, prefix="/api", tags=["kb"])
    app.include_router(docs.router, prefix="/api", tags=["docs"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.include_router(internal.router)

    _mount_mcp(app)

    return app


def _mount_mcp(app: FastAPI) -> None:
    from config.settings import get_settings

    cfg = get_settings().mcp
    if not cfg.enabled or cfg.transport == "stdio":
        return

    from mcp_server.server import create_mcp_server

    mcp_server = create_mcp_server()
    if cfg.transport == "streamable-http":
        # streamable_http_app() registers its endpoint at /mcp within the sub-app.
        # app.mount("/mcp", sub_app) would create a double-prefix /mcp/mcp.
        # Routes are added directly, and the sub-app's lifespan (which initializes
        # FastMCP's task group) is run via _lifespan using app.state.mcp_sub_app.
        mcp_sub_app = mcp_server.streamable_http_app()
        app.state.mcp_sub_app = mcp_sub_app
        for route in mcp_sub_app.routes:
            app.router.routes.append(route)
        logger.info("MCP server mounted: transport=streamable-http path=/mcp")
    elif cfg.transport == "sse":
        app.mount("/mcp", mcp_server.sse_app("/mcp"))
        logger.info("MCP server mounted: transport=sse path=/mcp")


def _register_exception_handlers(app: FastAPI) -> None:
    """Map exceptions to HTTP responses. Status code assignment lives here only."""

    @app.exception_handler(ClientError)
    async def s3_error_handler(_request: Request, exc: ClientError) -> JSONResponse:
        logger.error("S3 error: %s", exc)
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(redis_lib.RedisError)
    async def redis_error_handler(_request: Request, exc: redis_lib.RedisError) -> JSONResponse:
        logger.error("Redis error: %s", exc)
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(ConfigError)
    async def config_error_handler(_request: Request, exc: ConfigError) -> JSONResponse:
        logger.error("Config error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(IngestValidationError)
    async def ingest_validation_error_handler(_request: Request, exc: IngestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def not_found_error_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConflictError)
    async def conflict_error_handler(_request: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})


def _start_queue_worker(app: FastAPI) -> None:
    from config.settings import get_settings
    cfg = get_settings()
    if not cfg.queue_worker.enabled:
        return
    from pipeline.queue_worker import QueueWorker
    import asyncio
    worker = QueueWorker(
        max_workers=cfg.queue_worker.max_workers,
        poll_interval_sec=cfg.queue_poll.poll_interval_sec,
        max_per_poll=cfg.queue_poll.max_per_poll,
    )
    task = asyncio.create_task(worker.start())
    app.state.queue_worker_task = task
    logger.info(
        "QueueWorker started: max_workers=%d poll_interval=%ds max_per_poll=%d",
        cfg.queue_worker.max_workers, cfg.queue_poll.poll_interval_sec, cfg.queue_poll.max_per_poll,
    )


async def _init_infrastructure() -> None:
    """
    On startup:
    1. Ensure S3 bucket exists
    2. Auto-create knowledge_bases defined in settings.yaml
    """
    from config.settings import get_settings
    from infra.s3 import ensure_bucket
    from infra.qdrant import ensure_collection
    from infra.redis import list_kb_ids, register_kb

    cfg = get_settings()

    try:
        ensure_bucket()
    except Exception as e:
        logger.warning("S3 bucket init failed: %s", e)

    try:
        existing_kb_ids = set(list_kb_ids())
    except Exception as e:
        logger.warning("Redis unavailable, skipping KB auto-creation: %s", e)
        return

    for kb_def in cfg.knowledge_bases:
        try:
            if kb_def.id not in existing_kb_ids:
                register_kb(kb_def.id, kb_def.description)
                ensure_collection(kb_def.id)
                logger.info("KB auto-created: %s", kb_def.id)
        except Exception as e:
            logger.warning("KB init failed (%s): %s", kb_def.id, e)
