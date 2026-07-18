# MCP Server Design

## Overview

The MCP (Model Context Protocol) server exposes the RAG API's search capability as LLM-callable tools.
It is built on FastMCP and can run as a standalone process or embedded inside the FastAPI process.

---

## Transport Modes

| Mode | How to run | Endpoint |
|------|-----------|----------|
| `streamable-http` | Embedded in FastAPI (default in production) | `POST /mcp` |
| `sse` | Embedded in FastAPI (legacy) | `GET /mcp` |
| `stdio` | Standalone process (`python -m main serve-mcp`) | stdin/stdout |

The transport is selected by `mcp.transport` in `settings.yaml`.
In embedded mode the sub-app is mounted into FastAPI at startup via `_mount_mcp()` in `api/app.py`.
`stdio` transport is intended for local LLM client integrations (e.g. Claude Desktop).

---

## Architecture

```
LLM client (Claude, etc.)
    │  MCP protocol (streamable-http / SSE / stdio)
    ↓
FastMCP instance ("rag-api")
    │  instructions: "call list_knowledge_bases first, then search"
    ├── search()
    │     → retriever.search()   (Qdrant hybrid, multi-KB)
    │     → reranker.rerank_async()  (Jina API / RRF fallback)
    │     → {results, latency_ms}
    ├── list_knowledge_bases()
    │     → settings.knowledge_bases  (static config)
    │     → {knowledge_bases: [{id, description}]}
    └── get_document_status()
          → postgres.get_doc_status()
          → {status, updated_at, size_bytes, etag}
```

---

## Tools

### `search`

```
search(
    query:     str,
    kb_ids:    list[str] | None = None,   # omit to search all KBs
    top_k:     int | None = None,         # defaults to retrieval.top_k
    mode:      "hybrid" | "similarity" | None = None,
    min_score: float | None = None,       # similarity mode only
) -> {results: [...], latency_ms: int}
```

- Async tool. Calls `retriever.search()` then `reranker.rerank_async()`.
- If `kb_ids` is omitted, searches all KBs defined in `settings.knowledge_bases`.
- Each result item: `{text, score, rerank_score, kb_id, doc_key, page_num, page_label, chunk_idx}`.
- `rerank_score` is `null` when reranker is disabled or falls back to RRF.

### `list_knowledge_bases`

```
list_knowledge_bases() -> {knowledge_bases: [{id: str, description: str}]}
```

- Sync tool. Reads directly from `get_settings().knowledge_bases` — no I/O.
- Intended to be called first so the LLM client can discover valid `kb_ids`.

### `get_document_status`

```
get_document_status(
    kb_id:   str,
    doc_key: str,   # "{kb_id}___{doc_source}"
) -> {status, updated_at, size_bytes, etag}
```

- Sync tool. Reads from Postgres `documents` table via `postgres.get_doc_status()`.
- Returns `status: "not_found"` when the row does not exist.
- Status values: `pending | running | indexed | deleting | failed | not_found`.

---

## Tracing

Every tool is decorated with `@traced_tool` (`tracing/span.py`).
This wraps the tool in an OpenTelemetry span and sets RAG-specific attributes:

| Tool | Span attributes |
|------|----------------|
| `search` | `rag.query`, `rag.kb_ids`, `rag.result_count`, `rag.latency_ms` |
| `list_knowledge_bases` | `rag.kb_count` |
| `get_document_status` | `rag.kb_id`, `rag.doc_key`, `rag.doc_status` |

Tracing is a no-op when `tracing.enabled = false` (OpenTelemetry NoOp provider).
The FastAPI instrumentation excludes `/mcp` to avoid double-counting (`excluded_urls="/mcp$"`).

---

## Settings

```yaml
mcp:
  enabled:   true
  transport: streamable-http   # stdio | sse | streamable-http
  host:      "0.0.0.0"
  port:      8001              # used for standalone serve-mcp only
```

Setting `enabled: false` disables the MCP server entirely.
In embedded mode, `host` and `port` are ignored — FastAPI's own host/port applies.

---

## Startup

**Embedded (production):**

FastAPI factory `create_app()` calls `_mount_mcp(app)` during startup.
For `streamable-http`, the FastMCP sub-app is mounted by copying its routes directly onto the
FastAPI app (not via `app.mount("/mcp", ...)`) to avoid a double `/mcp/mcp` prefix.

**Standalone:**

```bash
python -m main serve-mcp --transport streamable-http --port 8001
python -m main serve-mcp --transport stdio
```

---

## Source Locations

| Item | File |
|------|------|
| FastMCP factory | `src/mcp_server/server.py` |
| `search` tool | `src/mcp_server/tools/search.py` |
| `list_knowledge_bases` tool | `src/mcp_server/tools/kb.py` |
| `get_document_status` tool | `src/mcp_server/tools/docs.py` |
| FastAPI mount logic | `src/api/app.py` — `_mount_mcp()` |
| CLI entry point | `src/main.py` — `serve_mcp()` |
| Tracing decorator | `src/tracing/span.py` — `traced_tool` |
| Settings | `src/config/settings.py` — `McpSettings` |
