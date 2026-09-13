"""FastAPI /api/search 엔드포인트 통합 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from rag_api.api.app import create_app
from rag_api.query.retriever import QueryResult


def _make_result(
    chunk_id: str, merged: bool = False, chunk_index: int | None = 0,
    parent_chunk_id: str | None = None,
) -> QueryResult:
    return QueryResult(
        chunk_id=chunk_id,
        kb_id="kb-test",
        doc_id="doc-id-1",
        title="doc.pdf",
        source="doc.pdf",
        doc_type="pdf",
        chunk_index=chunk_index,
        page_num=1,
        page_label="i",
        text="테스트 청크 내용",
        score=0.9,
        rerank_score=None,
        updated_at="2025-06-07T00:00:00Z",
        merged=merged,
        parent_chunk_id=parent_chunk_id,
    )


@pytest.fixture
def client():
    with patch("rag_api.api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


def test_search_returns_results(client):
    from unittest.mock import MagicMock

    mock_results = [_make_result(f"chunk-{i}") for i in range(3)]

    # Override settings so reranking is enabled (settings.yaml may have it disabled)
    mock_settings = MagicMock()
    mock_settings.retrieval.mode = "hybrid"
    mock_settings.retrieval.rerank.enabled = True
    mock_settings.retrieval.similarity.min_score = 0.0
    mock_settings.search_cache.enabled = False

    with (
        patch("rag_api.query.retriever.query", new=AsyncMock(return_value=(mock_results[:2], 3, "jina", False))),
        patch("rag_api.config.settings.get_settings", return_value=mock_settings),
    ):
        resp = client.post(
            "/api/search",
            json={
                "query": "Keycloak 설정",
                "kb_ids": ["kb-test"],
                "options": {"top_k": 10, "rerank": {"enabled": True, "top_n": 2}},
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Keycloak 설정"
    assert len(data["results"]) == 2
    assert data["results"][0]["page_num"] == 1
    assert data["results"][0]["page_label"] == "i"
    assert data["meta"]["reranked"] is True
    assert data["meta"]["rerank_provider"] == "jina"
    assert data["meta"]["score_threshold"] == 0.0
    assert data["meta"]["cache_status"] == "disabled"


def test_search_empty_kb_ids(client):
    resp = client.post(
        "/api/search",
        json={"query": "테스트", "kb_ids": []},
    )
    assert resp.status_code == 422


def test_search_similarity_mode_with_min_score(client):
    from unittest.mock import MagicMock

    mock_results = [_make_result(f"chunk-{i}") for i in range(2)]

    mock_settings = MagicMock()
    mock_settings.retrieval.mode = "similarity"
    mock_settings.retrieval.rerank.enabled = False
    mock_settings.retrieval.similarity.min_score = 0.0
    mock_settings.search_cache.enabled = False

    with (
        patch("rag_api.query.retriever.query", new=AsyncMock(return_value=(mock_results, 2, "none", False))),
        patch("rag_api.config.settings.get_settings", return_value=mock_settings),
    ):
        resp = client.post(
            "/api/search",
            json={
                "query": "test query",
                "kb_ids": ["kb-test"],
                "options": {
                    "mode": "similarity",
                    "top_k": 5,
                    "similarity": {"min_score": 0.4},
                    "rerank": {"enabled": False, "top_n": 5},
                },
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["search_mode"] == "similarity"
    assert data["meta"]["score_threshold"] == 0.4


def test_search_invalid_mode_returns_422(client):
    resp = client.post(
        "/api/search",
        json={
            "query": "test",
            "kb_ids": ["kb-test"],
            "options": {"mode": "invalid"},
        },
    )
    assert resp.status_code == 422


def test_health_liveness(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


class TestSearchCacheIntegration:
    def _mock_settings(self, *, cache_enabled: bool, match_mode: str = "exact"):
        from unittest.mock import MagicMock

        mock_settings = MagicMock()
        mock_settings.retrieval.mode = "hybrid"
        mock_settings.retrieval.rerank.enabled = True
        mock_settings.retrieval.similarity.min_score = 0.0
        mock_settings.search_cache.enabled = cache_enabled
        mock_settings.search_cache.match_mode = match_mode
        return mock_settings

    # AC: F3-3, F3-4 (US-53-search-cache/T4)
    def test_cache_hit_skips_retriever_and_reports_hit(self, client):
        """캐시 hit이면 retriever.query가 호출되지 않고 meta.cache_status == 'hit'."""
        cached_response = {
            "query": "cached query",
            "results": [],
            "meta": {
                "total_candidates": 0, "returned": 0, "search_mode": "hybrid",
                "score_threshold": 0.0, "reranked": False, "rerank_provider": "none",
                "rerank_fallback": False, "latency_ms": 1, "cache_status": "miss",
            },
        }
        mock_settings = self._mock_settings(cache_enabled=True)
        mock_retriever_query = AsyncMock()

        with (
            patch("rag_api.config.settings.get_settings", return_value=mock_settings),
            patch("rag_api.query.retriever.query", new=mock_retriever_query),
            patch(
                "rag_api.query.search_cache.lookup",
                return_value=(cached_response, None),
            ),
            patch("rag_api.query.search_cache.store") as mock_store,
        ):
            resp = client.post(
                "/api/search",
                json={"query": "cached query", "kb_ids": ["kb-test"]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["cache_status"] == "hit"
        mock_retriever_query.assert_not_called()
        mock_store.assert_not_called()

    # AC: F3-3, F3-4 (US-53-search-cache/T4)
    def test_cache_miss_calls_retriever_and_stores(self, client):
        """캐시 miss면 retriever를 호출해 응답을 만들고, meta.cache_status == 'miss'로 저장한다."""
        mock_results = [_make_result("chunk-0")]
        mock_settings = self._mock_settings(cache_enabled=True)

        with (
            patch("rag_api.config.settings.get_settings", return_value=mock_settings),
            patch(
                "rag_api.query.retriever.query",
                new=AsyncMock(return_value=(mock_results, 1, "jina", False)),
            ),
            patch("rag_api.query.search_cache.lookup", return_value=(None, None)) as mock_lookup,
            patch("rag_api.query.search_cache.store") as mock_store,
        ):
            resp = client.post(
                "/api/search",
                json={"query": "new query", "kb_ids": ["kb-test"]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["cache_status"] == "miss"
        mock_lookup.assert_called_once()
        mock_store.assert_called_once()

    # AC: F1-2 (US-53-search-cache/T4)
    def test_cache_disabled_skips_lookup_and_store(self, client):
        """search_cache.enabled=False면 lookup/store를 아예 호출하지 않는다."""
        mock_results = [_make_result("chunk-0")]
        mock_settings = self._mock_settings(cache_enabled=False)

        with (
            patch("rag_api.config.settings.get_settings", return_value=mock_settings),
            patch(
                "rag_api.query.retriever.query",
                new=AsyncMock(return_value=(mock_results, 1, "jina", False)),
            ),
            patch("rag_api.query.search_cache.lookup") as mock_lookup,
            patch("rag_api.query.search_cache.store") as mock_store,
        ):
            resp = client.post(
                "/api/search",
                json={"query": "any query", "kb_ids": ["kb-test"]},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["cache_status"] == "disabled"
        mock_lookup.assert_not_called()
        mock_store.assert_not_called()