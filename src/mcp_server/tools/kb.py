"""MCP tool: list_knowledge_bases."""

from __future__ import annotations

from typing import Any

from config.settings import get_settings


def list_knowledge_bases() -> dict[str, Any]:
    """List all available knowledge bases with their IDs and descriptions."""
    kbs = get_settings().knowledge_bases
    return {
        "knowledge_bases": [{"id": kb.id, "description": kb.description} for kb in kbs]
    }
