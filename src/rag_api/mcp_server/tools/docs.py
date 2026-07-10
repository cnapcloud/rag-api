"""MCP tool: get_document_status."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from opentelemetry import trace

from rag_api.infra.postgres import get_doc_by_id
from rag_api.tracing.span import traced_tool


@traced_tool
def get_document_status(kb_id: str, doc_id: str, ctx: Context | None = None) -> dict[str, Any]:
    """Check the indexing status of a document by its doc_id.

    Returns status (uploading | fetching | pending | running | indexed | deleting | deleted | failed | not_found),
    updated_at timestamp, file_size, and content_version when available.
    """
    span = trace.get_current_span()
    span.set_attribute("rag.kb_id", kb_id)
    span.set_attribute("rag.doc_id", doc_id)

    doc = get_doc_by_id(doc_id)
    if doc is None or doc.get("kb_id") != kb_id:
        span.set_attribute("rag.doc_status", "not_found")
        return {"status": "not_found", "updated_at": None, "file_size": None, "content_version": None}

    status = doc.get("status", "unknown")
    span.set_attribute("rag.doc_status", status)
    return {
        "status": status,
        "updated_at": doc.get("updated_at"),
        "file_size": int(doc["file_size"]) if doc.get("file_size") else None,
        "content_version": doc.get("content_version"),
    }
