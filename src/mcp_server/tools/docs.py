"""MCP tool: get_document_status."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from opentelemetry import trace

from infra.postgres import get_doc_status
from tracing.span import traced_tool


@traced_tool
def get_document_status(kb_id: str, doc_key: str, ctx: Context | None = None) -> dict[str, Any]:
    """Check the indexing status of a document in a knowledge base.

    Returns status (pending | processing | indexed | error | not_found),
    updated_at timestamp, size_bytes, and etag when available.
    """
    span = trace.get_current_span()
    span.set_attribute("rag.kb_id", kb_id)
    span.set_attribute("rag.doc_key", doc_key)

    data = get_doc_status(kb_id, doc_key)
    if not data:
        span.set_attribute("rag.doc_status", "not_found")
        return {"status": "not_found", "updated_at": None, "size_bytes": None, "etag": None}

    status = data.get("status", "unknown")
    span.set_attribute("rag.doc_status", status)
    return {
        "status": status,
        "updated_at": data.get("updated_at"),
        "size_bytes": int(data["size_bytes"]) if data.get("size_bytes") else None,
        "etag": data.get("etag"),
    }
