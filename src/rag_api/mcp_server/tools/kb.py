"""MCP tool: list_knowledge_bases."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from opentelemetry import trace

from rag_api.infra.postgres import list_kbs
from rag_api.tracing.span import traced_tool


@traced_tool
def list_knowledge_bases(ctx: Context | None = None) -> dict[str, Any]:
    """List all available knowledge bases with their IDs, names, descriptions, and tags."""
    span = trace.get_current_span()
    kbs = list_kbs()
    span.set_attribute("rag.kb_count", len(kbs))
    return {
        "knowledge_bases": [
            {
                "id": kb["kb_id"],
                "name": kb["kb_name"],
                "description": kb["description"],
                "tags": kb["tags"],
            }
            for kb in kbs
        ]
    }
