"""MCP tool: list_knowledge_bases."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context
from opentelemetry import trace

from config.settings import get_settings
from tracing.span import traced_tool


@traced_tool
def list_knowledge_bases(ctx: Context | None = None) -> dict[str, Any]:
    """List all available knowledge bases with their IDs and descriptions."""
    span = trace.get_current_span()
    kbs = get_settings().knowledge_bases
    span.set_attribute("rag.kb_count", len(kbs))
    return {
        "knowledge_bases": [{"id": kb.id, "description": kb.description} for kb in kbs]
    }
