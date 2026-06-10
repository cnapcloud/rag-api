"""MCP tool: get_document_status."""

from __future__ import annotations

from typing import Any

from infra.redis import get_doc_status


def get_document_status(kb_id: str, doc_key: str) -> dict[str, Any]:
    """Check the indexing status of a document in a knowledge base.

    Returns status (pending | processing | indexed | error | not_found),
    indexed_at timestamp, size_bytes, and etag when available.
    """
    data = get_doc_status(kb_id, doc_key)
    if not data:
        return {"status": "not_found", "indexed_at": None, "size_bytes": None, "etag": None}

    return {
        "status": data.get("status", "unknown"),
        "indexed_at": data.get("indexed_at"),
        "size_bytes": int(data["size_bytes"]) if data.get("size_bytes") else None,
        "etag": data.get("etag"),
    }
