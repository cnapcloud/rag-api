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
    from config.settings import get_settings
    level = getattr(logging, get_settings().logging.level.upper(), logging.INFO)
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
    """Upload file to S3 then trigger ingest (Dagster queue or direct)."""
    if not file.exists():
        typer.echo(f"File not found: {file}", err=True)
        raise typer.Exit(1)

    from infra.s3 import upload_object

    content = file.read_bytes()
    import mimetypes
    content_type = mimetypes.guess_type(str(file))[0] or "application/octet-stream"

    typer.echo(f"Uploading to S3: kb={kb_id} key={file.name}")
    etag = upload_object(kb_id=kb_id, object_key=file.name, data=content, content_type=content_type)
    typer.echo(f"Uploaded: etag={etag}")

    from dagster_pipeline.sensors.event_queue_sensor import enqueue_upload_event

    enqueue_upload_event(kb_id=kb_id, object_key=file.name, etag=etag, file_size=len(content), force=force)
    typer.echo(f"Queued for ingest: kb={kb_id} key={file.name}")


# ──────────────────────────────────────────────
# serve
# ──────────────────────────────────────────────

@app.command("serve-mcp")
def serve_mcp(
    transport: Optional[str] = typer.Option(None, "--transport", help="stdio | sse | streamable-http (overrides settings.yaml)"),
    port: Optional[int] = typer.Option(None, "--port", help="HTTP port for sse/streamable-http (overrides settings.yaml)"),
):
    """Start the MCP server (stdio, SSE, or streamable-http transport)."""
    from config.settings import get_settings
    from mcp_server.server import create_mcp_server

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
def serve(
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
):
    """FastAPI 서버 실행."""
    import uvicorn

    from api.app import create_app

    uvicorn.run(
        "api.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )


# ──────────────────────────────────────────────
# search
# ──────────────────────────────────────────────

@app.command()
def search(
    kb_ids: list[str] = typer.Option(..., "--kb-ids", help="검색할 KB ID 목록"),
    query: str = typer.Option(..., "--query", help="검색 쿼리"),
    top_k: int = typer.Option(10, "--top-k"),
    rerank: bool = typer.Option(True, "--rerank/--no-rerank"),
):
    """Hybrid Search 직접 실행 (CLI 테스트용)."""
    import asyncio

    from rag.retriever import hybrid_search

    results = asyncio.run(hybrid_search(query=query, kb_ids=kb_ids, top_k=top_k))

    if rerank and results:
        from rag.reranker import rerank as do_rerank

        results, provider, fallback = do_rerank(query=query, results=results)
        typer.echo(f"Reranker: {provider} (fallback={fallback})")

    typer.echo(f"\n검색 결과 ({len(results)}건):\n")
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
    description: str = typer.Option("", "--description"),
):
    """KB 생성 (Redis + Qdrant)."""
    from infra.qdrant import ensure_collection
    from infra.redis import register_kb

    register_kb(kb_id, description)
    ensure_collection(kb_id)
    typer.echo(f"KB 생성 완료: {kb_id}")


@kb_app.command("list")
def kb_list():
    """KB 목록 조회."""
    from infra.redis import list_kb_ids

    ids = list_kb_ids()
    if not ids:
        typer.echo("KB가 없습니다.")
        return
    for kb_id in sorted(ids):
        typer.echo(f"  - {kb_id}")


@kb_app.command("delete")
def kb_delete(kb_id: str = typer.Option(..., "--kb-id")):
    """KB 삭제 (Qdrant + S3 + Redis)."""
    from infra.s3 import delete_kb_prefix
    from infra.qdrant import drop_collection
    from infra.redis import delete_kb_meta

    drop_collection(kb_id)
    delete_kb_prefix(kb_id)
    delete_kb_meta(kb_id)
    typer.echo(f"KB 삭제 완료: {kb_id}")



if __name__ == "__main__":
    app()