"""reranker.py — jina/internal provider 분기 + fallback 단위 테스트."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rag_api.config.settings import Settings
from rag_api.rag.reranker import rerank_async
from rag_api.rag.retriever import SearchResult


def _make_result(chunk_id: str, text: str, score: float) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        kb_id="kb-test",
        doc_id="doc-1",
        doc_type="pdf",
        title="doc.pdf",
        chunk_index=0,
        page_num=1,
        page_label="1",
        text=text,
        score=score,
        rerank_score=None,
        updated_at="2025-06-07T00:00:00Z",
    )


def _mock_async_client(response_json: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value=response_json)

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
async def test_rerank_internal_provider_calls_base_url() -> None:
    settings = Settings.model_validate(
        {
            "retrieval": {
                "rerank": {
                    "enabled": True,
                    "provider": "internal",
                    "base_url": "http://reranker:8080/rerank",
                    "top_n": 2,
                }
            }
        }
    )
    results = [
        _make_result("chunk-0", "first", 0.5),
        _make_result("chunk-1", "second", 0.4),
    ]
    response_json = {
        "results": [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.3},
        ]
    }
    mock_client = _mock_async_client(response_json)

    with (
        patch("rag_api.rag.reranker.get_settings", return_value=settings),
        patch("rag_api.rag.reranker.httpx.AsyncClient", return_value=mock_client),
    ):
        reranked, provider, fallback_used = await rerank_async("query", results)

    assert provider == "internal"
    assert fallback_used is False
    assert [r.chunk_id for r in reranked] == ["chunk-1", "chunk-0"]
    mock_client.post.assert_awaited_once()
    called_url = mock_client.post.await_args.args[0]
    assert called_url == "http://reranker:8080/rerank"


@pytest.mark.asyncio
async def test_rerank_internal_provider_without_base_url_falls_back() -> None:
    settings = Settings.model_validate(
        {
            "retrieval": {
                "rerank": {
                    "enabled": True,
                    "provider": "internal",
                    "base_url": "",
                    "fallback_on_error": True,
                }
            }
        }
    )
    results = [
        _make_result("chunk-0", "first", 0.5),
        _make_result("chunk-1", "second", 0.9),
    ]

    with patch("rag_api.rag.reranker.get_settings", return_value=settings):
        reranked, provider, fallback_used = await rerank_async("query", results)

    assert provider == "internal"
    assert fallback_used is True
    assert [r.chunk_id for r in reranked] == ["chunk-1", "chunk-0"]


@pytest.mark.asyncio
async def test_rerank_unknown_provider_falls_back() -> None:
    # provider is a Literal["jina", "internal"] on Settings — an unsupported value can only
    # reach reranker.py if some other caller bypasses that validation, so this builds the cfg
    # object directly instead of through Settings.model_validate (which would itself reject it).
    fake_settings = SimpleNamespace(
        retrieval=SimpleNamespace(
            rerank=SimpleNamespace(
                enabled=True,
                provider="cohere",
                base_url="",
                api_key="",
                model="",
                top_n=3,
                timeout_sec=5,
                fallback_on_error=True,
            )
        )
    )
    results = [_make_result("chunk-0", "first", 0.2)]

    with patch("rag_api.rag.reranker.get_settings", return_value=fake_settings):
        reranked, provider, fallback_used = await rerank_async("query", results)

    assert provider == "cohere"
    assert fallback_used is True
    assert [r.chunk_id for r in reranked] == ["chunk-0"]
