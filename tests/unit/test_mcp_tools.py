"""Unit tests for MCP tool functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.tools.docs import get_document_status
from mcp_server.tools.kb import list_knowledge_bases
from mcp_server.tools.search import search


# ──────────────────────────────────────────────
# list_knowledge_bases
# ──────────────────────────────────────────────

def test_list_knowledge_bases_returns_all():
    fake_settings = MagicMock()
    fake_settings.knowledge_bases = [
        MagicMock(id="kb-a", description="Alpha KB"),
        MagicMock(id="kb-b", description="Beta KB"),
    ]

    with patch("mcp_server.tools.kb.get_settings", return_value=fake_settings):
        result = list_knowledge_bases()

    assert result == {
        "knowledge_bases": [
            {"id": "kb-a", "description": "Alpha KB"},
            {"id": "kb-b", "description": "Beta KB"},
        ]
    }


def test_list_knowledge_bases_empty():
    fake_settings = MagicMock()
    fake_settings.knowledge_bases = []

    with patch("mcp_server.tools.kb.get_settings", return_value=fake_settings):
        result = list_knowledge_bases()

    assert result == {"knowledge_bases": []}


# ──────────────────────────────────────────────
# get_document_status
# ──────────────────────────────────────────────

def test_get_document_status_indexed():
    with patch("mcp_server.tools.docs.get_doc_status") as mock_get:
        mock_get.return_value = {
            "status": "indexed",
            "updated_at": "2026-06-08T00:00:00Z",
            "size_bytes": "12345",
            "etag": "abc123",
        }
        result = get_document_status("kb-a", "doc.pdf")

    assert result["status"] == "indexed"
    assert result["size_bytes"] == 12345
    assert result["etag"] == "abc123"
    assert result["updated_at"] == "2026-06-08T00:00:00Z"


def test_get_document_status_not_found():
    with patch("mcp_server.tools.docs.get_doc_status", return_value=None):
        result = get_document_status("kb-a", "missing.pdf")

    assert result == {"status": "not_found", "updated_at": None, "size_bytes": None, "etag": None}


def test_get_document_status_no_size():
    with patch("mcp_server.tools.docs.get_doc_status") as mock_get:
        mock_get.return_value = {"status": "running", "updated_at": None}
        result = get_document_status("kb-a", "doc.pdf")

    assert result["status"] == "running"
    assert result["size_bytes"] is None


# ──────────────────────────────────────────────
# search
# ──────────────────────────────────────────────

def _make_result(text="hello", kb_id="kb-a", doc_key="doc.pdf", score=0.9):
    from rag.retriever import SearchResult
    return SearchResult(
        chunk_id="chunk-1",
        kb_id=kb_id,
        doc_key=doc_key,
        doc_type="pdf",
        chunk_index=0,
        page_num=1,
        text=text,
        score=score,
        rerank_score=None,
        updated_at="2026-06-08T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_search_with_explicit_kb_ids():
    fake_settings = MagicMock()
    fake_settings.knowledge_bases = []

    candidate = _make_result()
    reranked = _make_result()
    reranked.rerank_score = 0.95

    with (
        patch("mcp_server.tools.search.get_settings", return_value=fake_settings),
        patch("mcp_server.tools.search.hybrid_search", new=AsyncMock(return_value=[candidate])),
        patch("mcp_server.tools.search.rerank_async", new=AsyncMock(return_value=([reranked], "jina", False))),
    ):
        result = await search(query="what is TDF?", kb_ids=["kb-a"], top_k=5)

    assert len(result["results"]) == 1
    assert result["results"][0]["kb_id"] == "kb-a"
    assert result["results"][0]["rerank_score"] == 0.95
    assert "latency_ms" in result


@pytest.mark.asyncio
async def test_search_expands_to_all_kbs_when_none_specified():
    fake_settings = MagicMock()
    fake_settings.knowledge_bases = [
        MagicMock(id="kb-a"),
        MagicMock(id="kb-b"),
    ]

    with (
        patch("mcp_server.tools.search.get_settings", return_value=fake_settings),
        patch("mcp_server.tools.search.hybrid_search", new=AsyncMock(return_value=[])) as mock_search,
        patch("mcp_server.tools.search.rerank_async", new=AsyncMock(return_value=([], "none", False))),
    ):
        await search(query="hello")

    called_kb_ids = mock_search.call_args.kwargs["kb_ids"]
    assert set(called_kb_ids) == {"kb-a", "kb-b"}


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_kbs():
    fake_settings = MagicMock()
    fake_settings.knowledge_bases = []

    with patch("mcp_server.tools.search.get_settings", return_value=fake_settings):
        result = await search(query="hello")

    assert result == {"results": [], "latency_ms": 0}
