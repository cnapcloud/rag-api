"""FastAPI app factory + startup events + global exception handlers."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import psycopg
import redis as redis_lib
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from rag_api.api.routers import connectors, docs, health, kb, search
from rag_api.exceptions import ConfigError, ConflictError, IngestValidationError, NotFoundError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from rag_api.tracing.setup import init_tracing, shutdown_tracing

    init_tracing()
    try:
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
    finally:
        shutdown_tracing()


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG API",
        description="LlamaIndex + Dagster RAG pipeline API",
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
    app.include_router(connectors.router, prefix="/api/connectors", tags=["connectors"])

    _mount_mcp(app)
    _instrument_tracing(app)

    return app


def _mount_mcp(app: FastAPI) -> None:
    from rag_api.config.settings import get_settings

    cfg = get_settings().mcp
    if not cfg.enabled or cfg.transport == "stdio":
        return

    from rag_api.mcp_server.server import create_mcp_server

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


def _instrument_tracing(app: FastAPI) -> None:
    from rag_api.config.settings import get_settings

    if not get_settings().tracing.enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/health,/ready,/status$",
        exclude_spans=["receive", "send"],
    )
    logger.info(
        "FastAPI tracing instrumentation enabled (excluded_urls: /health,/ready,/status;"
        " exclude_spans: receive,send)"
    )


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

    @app.exception_handler(psycopg.Error)
    async def postgres_error_handler(_request: Request, exc: psycopg.Error) -> JSONResponse:
        logger.error("Postgres error: %s", exc)
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

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(_request: Request, exc: RuntimeError) -> JSONResponse:
        logger.error("Unexpected runtime error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": str(exc)})


def _start_queue_worker(app: FastAPI) -> None:
    from rag_api.config.settings import get_settings
    cfg = get_settings()
    if not cfg.queue_worker.enabled:
        return
    import asyncio

    from rag_api.pipeline.queue.queue_worker import QueueWorker
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
    1. Run Postgres migrations
    2. Ensure S3 bucket exists
    3. Auto-create knowledge_bases defined in settings.yaml
    """
    from rag_api.config.settings import get_settings
    from rag_api.infra.postgres import list_kb_ids, register_kb, run_migrations
    from rag_api.infra.qdrant import ensure_collection
    from rag_api.infra.s3 import ensure_bucket

    cfg = get_settings()

    run_migrations()

    try:
        ensure_bucket()
    except Exception as e:
        logger.warning("S3 bucket init failed: %s", e)

    try:
        existing_kb_ids = set(list_kb_ids())
    except Exception as e:
        logger.warning("Postgres unavailable, skipping KB auto-creation: %s", e)
        return

    for kb_def in cfg.knowledge_bases:
        try:
            if kb_def.id not in existing_kb_ids:
                register_kb(kb_def.id, kb_def.name, kb_def.description, kb_def.tags)
                ensure_collection(kb_def.id)
                logger.info("KB auto-created: %s", kb_def.id)
        except Exception as e:
            logger.warning("KB init failed (%s): %s", kb_def.id, e)
