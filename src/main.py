"""CLI entrypoint placeholder (typer).
Run as: python -m main ingest|serve|search

RAG API — CLI 진입점.

사용법:
    python -m main ingest --kb-id kb-01 --file ./data/ATD00002_2605.pdf
    python -m main serve
    python -m main search --kb-ids kb-01 --query "TDF 상품"
    python -m main kb create --kb-id kb-new --description "New KB"
    python -m main serve-mcp --transport streamable-http --port 8001
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

def _configure_logging() -> None:
    from rag_api.config.settings import get_settings

    cfg = get_settings()
    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)

    if cfg.tracing.enabled:
        from rag_api.tracing import OtelContextFilter

        fmt = "%(asctime)s %(levelname)s [%(trace_id)s:%(span_id)s] %(name)s: %(message)s"
        logging.basicConfig(level=level, format=fmt, datefmt="%Y-%m-%d %H:%M:%S")
        otel_filter = OtelContextFilter()
        for handler in logging.getLogger().handlers:
            handler.addFilter(otel_filter)
    else:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

_configure_logging()

app = typer.Typer(help="CNAP RAG Pipeline CLI")
kb_app = typer.Typer(help="KB 관리")
app.add_typer(kb_app, name="kb")


# ──────────────────────────────────────────────
# ingest
# ──────────────────────────────────────────────

@app.command()
def ingest(
    kb_id: str = typer.Option(..., "--kb-id", help="Knowledge Base ID"),
    file: Path = typer.Option(..., "--file", help="Local file path to ingest"),
    force: bool = typer.Option(False, "--force/--no-force", help="Skip ETag check and re-index"),
):
    """Upload file to S3 then enqueue for ingest."""
    if not file.exists():
        typer.echo(f"File not found: {file}", err=True)
        raise typer.Exit(1)

    import mimetypes

    from rag_api.infra.postgres import create_doc, get_doc_by_source, list_kb_ids
    from rag_api.infra.s3 import upload_object
    from rag_api.pipeline.queue.enqueue import enqueue_upload_event
    from rag_api.pipeline.utils.doc_state import set_pending, set_uploading
    from rag_api.pipeline.utils import normalize_source_uri

    if kb_id not in list_kb_ids():
        typer.echo(f"KB not found: {kb_id}", err=True)
        raise typer.Exit(1)

    content = file.read_bytes()
    content_type = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
    file_size = len(content)
    doc_type = file.suffix.lstrip(".").lower()
    source_uri = normalize_source_uri("s3", file.name)
    storage_key = f"{kb_id}/{file.name}"

    existing = get_doc_by_source(kb_id, source_uri)
    if existing is None:
        doc = create_doc(
            kb_id=kb_id,
            source=source_uri,
            title=file.name,
            source_type="s3",
            status="uploading",
            storage_key=storage_key,
            file_size=file_size,
            doc_type=doc_type,
        )
    else:
        doc = existing
        set_uploading(doc["doc_id"], file_size=file_size, storage_key=storage_key)

    doc_id: str = doc["doc_id"]

    typer.echo(f"Uploading to S3: kb={kb_id} key={file.name}")
    etag = upload_object(kb_id=kb_id, source=file.name, data=content, content_type=content_type)
    typer.echo(f"Uploaded: etag={etag}")

    set_pending(doc_id, content_version=etag)
    enqueue_upload_event(doc_id=doc_id, force=force)
    typer.echo(f"Queued for ingest: kb={kb_id} doc_id={doc_id} force={force}")


# ──────────────────────────────────────────────
# serve
# ──────────────────────────────────────────────

@app.command("serve-mcp")
def serve_mcp(
    transport: Optional[str] = typer.Option(None, "--transport", help="stdio | sse | streamable-http (overrides settings.yaml)"),
    port: Optional[int] = typer.Option(None, "--port", help="HTTP port for sse/streamable-http (overrides settings.yaml)"),
):
    """Start the MCP server (stdio, SSE, or streamable-http transport)."""
    from rag_api.config.settings import get_settings
    from rag_api.mcp_server.server import create_mcp_server

    cfg = get_settings().mcp
    if not cfg.enabled:
        typer.echo("MCP server is disabled (mcp.enabled=false in settings.yaml).", err=True)
        raise typer.Exit(1)

    _transport = transport or cfg.transport
    _port = port or cfg.port

    uses_http = _transport in ("sse", "streamable-http")

    if not uses_http:
        # stdio transport: MCP protocol owns stdin/stdout.
        # Redirect stdout to stderr so any stray print() cannot corrupt the stream.
        import sys
        sys.stdout = sys.stderr
        typer.echo("Starting MCP server: transport=stdio", err=True)
    else:
        typer.echo(f"Starting MCP server: transport={_transport} host={cfg.host} port={_port} path=/mcp")

    server = create_mcp_server(port=_port if uses_http else None)

    server.run(transport=_transport)


@app.command()
def migrate():
    """Apply pending Postgres schema migrations."""
    from rag_api.infra.postgres import run_migrations

    run_migrations()
    typer.echo("Migrations applied.")


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
):
    """FastAPI 서버 실행."""
    import uvicorn

    uvicorn.run(
        "rag_api.api.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
        log_config=None,
    )


# ──────────────────────────────────────────────
# search
# ──────────────────────────────────────────────

@app.command()
def search(
    kb_ids: list[str] = typer.Option(..., "--kb-ids", help="KB ID list to search"),
    query: str = typer.Option(..., "--query", help="Search query"),
    top_k: int = typer.Option(10, "--top-k"),
    rerank: bool = typer.Option(True, "--rerank/--no-rerank"),
):
    """Hybrid search (CLI test)."""
    import asyncio

    from rag_api.rag import search as retriever_search

    results, total, provider, fallback = asyncio.run(
        retriever_search(query=query, kb_ids=kb_ids, top_k=top_k, rerank_enabled=rerank)
    )

    if provider != "none":
        typer.echo(f"Reranker: {provider} (fallback={fallback})")

    typer.echo(f"\nSearch results ({len(results)} of {total}):\n")
    for i, r in enumerate(results, 1):
        typer.echo(f"[{i}] score={r.score:.4f} | {r.doc_key} | chunk={r.chunk_index}")
        typer.echo(f"    {r.text[:200]}")
        typer.echo()


# ──────────────────────────────────────────────
# kb 서브커맨드
# ──────────────────────────────────────────────

@kb_app.command("create")
def kb_create(
    kb_id: str = typer.Option(..., "--kb-id"),
    kb_name: str = typer.Option("", "--kb-name"),
    description: str | None = typer.Option(None, "--description"),
    tags: list[str] = typer.Option([], "--tag"),
):
    """KB 생성 (Postgres + Qdrant)."""
    from rag_api.infra.postgres import register_kb
    from rag_api.infra.qdrant import ensure_collection

    register_kb(kb_id, kb_name, description, tags)
    ensure_collection(kb_id)
    typer.echo(f"KB created: {kb_id}")


@kb_app.command("list")
def kb_list():
    """KB 목록 조회."""
    from rag_api.infra.postgres import list_kb_ids

    ids = list_kb_ids()
    if not ids:
        typer.echo("No knowledge bases found.")
        return
    for kb_id in sorted(ids):
        typer.echo(f"  - {kb_id}")


@kb_app.command("delete")
def kb_delete(kb_id: str = typer.Option(..., "--kb-id")):
    """KB 삭제 (Qdrant + S3 + Postgres)."""
    from rag_api.infra.postgres import delete_kb_meta
    from rag_api.infra.qdrant import drop_collection
    from rag_api.infra.s3 import delete_kb_prefix

    drop_collection(kb_id)
    delete_kb_prefix(kb_id)
    delete_kb_meta(kb_id)
    typer.echo(f"KB deleted: {kb_id}")



if __name__ == "__main__":
    app()