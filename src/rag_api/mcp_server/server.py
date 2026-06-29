"""MCP server factory — FastMCP instance with tool registration."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from rag_api.mcp_server.tools.docs import get_document_status
from rag_api.mcp_server.tools.kb import list_knowledge_bases
from rag_api.mcp_server.tools.search import search

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "Use these tools to search company knowledge bases. "
    "Call list_knowledge_bases first to discover available KB IDs, "
    "then call search with the relevant kb_ids and the user's query."
)


def create_mcp_server(host: str | None = None, port: int | None = None) -> FastMCP:
    from rag_api.config.settings import get_settings

    cfg = get_settings().mcp
    server = FastMCP(
        "rag-api",
        instructions=_INSTRUCTIONS,
        host=host or cfg.host,
        port=port or cfg.port,
    )

    server.add_tool(search)
    server.add_tool(list_knowledge_bases)
    server.add_tool(get_document_status)

    logger.info("MCP server created: tools=search,list_knowledge_bases,get_document_status")
    return server
