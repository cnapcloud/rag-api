"""Unit tests for MCP tool functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rag_api.mcp_server.tools.docs import get_document_status
from rag_api.mcp_server.tools.kb import list_knowledge_bases
from rag_api.mcp_server.tools.search import search

DOC_ID = "11111111-1111-1111-1111-111111111111"


# ──────────────────────────────────────────────
# list_knowledge_bases
# ──────────────────────────────────────────────

def test_list_knowledge_bases_returns_all():
    fake_kbs = [
        {"kb_id": "kb-a", "kb_name": "Alpha", "description": "Alpha KB", "tags": ["eng"]},
        {"kb_id": "kb-b", "kb_name": "Beta", "description": "Beta KB", "tags": []},
    ]

    with patch("rag_api.mcp_server.tools.kb.list_kbs", return_value=fake_kbs):
        result = list_knowledge_bases()

    assert result == {
        "knowledge_bases": [
            {"id": "kb-a", "name": "Alpha", "description": "Alpha KB", "tags": ["eng"]},
            {"id": "kb-b", "name": "Beta", "description": "Beta KB", "tags": []},
        ]
    }


def test_list_knowledge_bases_empty():
    with patch("rag_api.mcp_server.tools.kb.list_kbs", return_value=[]):
        result = list_knowledge_bases()

    assert result == {"knowledge_bases": []}


# ──────────────────────────────────────────────
# get_document_status
# ──────────────────────────────────────────────

def test_get_document_status_indexed():
    with patch("rag_api.mcp_server.tools.docs.get_doc_by_id") as mock_get:
        mock_get.return_value = {
            "doc_id": DOC_ID,
            "kb_id": "kb-a",
            "status": "indexed",
            "updated_at": "2026-06-08T00:00:00Z",
            "file_size": 12345,
            "content_version": "abc123",
        }
        result = get_document_status("kb-a", DOC_ID)

    assert result["status"] == "indexed"
    assert result["file_size"] == 12345
    assert result["content_version"] == "abc123"
    assert result["updated_at"] == "2026-06-08T00:00:00Z"


def test_get_document_status_not_found():
    with patch("rag_api.mcp_server.tools.docs.get_doc_by_id", return_value=None):
        result = get_document_status("kb-a", DOC_ID)

    assert result == {"status": "not_found", "updated_at": None, "file_size": None, "content_version": None}


def test_get_document_status_kb_mismatch_is_not_found():
    with patch("rag_api.mcp_server.tools.docs.get_doc_by_id") as mock_get:
        mock_get.return_value = {"doc_id": DOC_ID, "kb_id": "kb-other", "status": "indexed", "file_size": None}
        result = get_document_status("kb-a", DOC_ID)

    assert result["status"] == "not_found"


def test_get_document_status_no_size():
    with patch("rag_api.mcp_server.tools.docs.get_doc_by_id") as mock_get:
        mock_get.return_value = {"doc_id": DOC_ID, "kb_id": "kb-a", "status": "running", "updated_at": None, "file_size": None, "content_version": None}
        result = get_document_status("kb-a", DOC_ID)

    assert result["status"] == "running"
    assert result["file_size"] is None


# ──────────────────────────────────────────────
# search
# ──────────────────────────────────────────────

def _make_result(text="hello", kb_id="kb-a", source="doc.pdf", score=0.9):
    from rag_api.rag.retriever import SearchResult
    return SearchResult(
        chunk_id="chunk-1",
        kb_id=kb_id,
        doc_id="doc-id-1",
        title="doc.pdf",
        source_type="s3",
        source=source,
        doc_type="pdf",
        chunk_index=0,
        page_num=1,
        page_label=None,
        text=text,
        score=score,
        rerank_score=None,
        updated_at="2026-06-08T00:00:00Z",
    )


@pytest.mark.asyncio
async def test_search_with_explicit_kb_ids():
    fake_settings = MagicMock()
    fake_settings.knowledge_bases = []

    reranked = _make_result()
    reranked.rerank_score = 0.95

    with (
        patch("rag_api.mcp_server.tools.search.get_settings", return_value=fake_settings),
        patch("rag_api.mcp_server.tools.search.retriever_search", new=AsyncMock(return_value=([reranked], 1, "jina", False))),
    ):
        result = await search(query="what is TDF?", kb_ids=["kb-a"], top_k=5)

    assert len(result["results"]) == 1
    assert result["results"][0]["kb_id"] == "kb-a"
    assert result["results"][0]["rerank_score"] == 0.95
    assert "latency_ms" in result


@pytest.mark.asyncio
async def test_search_expands_to_all_kbs_when_none_specified():
    with (
        patch("rag_api.mcp_server.tools.search.list_kb_ids", return_value=["kb-a", "kb-b"]),
        patch("rag_api.mcp_server.tools.search.retriever_search", new=AsyncMock(return_value=([], 0, "none", False))) as mock_search,
    ):
        await search(query="hello")

    called_kb_ids = mock_search.call_args.kwargs["kb_ids"]
    assert set(called_kb_ids) == {"kb-a", "kb-b"}


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_kbs():
    with patch("rag_api.mcp_server.tools.search.list_kb_ids", return_value=[]):
        result = await search(query="hello")

    assert result == {"results": [], "latency_ms": 0}
