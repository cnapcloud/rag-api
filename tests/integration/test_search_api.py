"""FastAPI /api/search 엔드포인트 통합 테스트."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from rag.retriever import SearchResult


def _make_result(chunk_id: str) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        kb_id="kb-test",
        doc_key="kb-test/doc.pdf",
        doc_type="pdf",
        chunk_index=0,
        page_num=1,
        text="테스트 청크 내용",
        score=0.9,
        rerank_score=None,
        indexed_at="2025-06-07T00:00:00Z",
    )


@pytest.fixture
def client():
    with patch("api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


def test_search_returns_results(client):
    from unittest.mock import MagicMock

    mock_results = [_make_result(f"chunk-{i}") for i in range(3)]

    # Override settings so reranking is enabled (settings.yaml may have it disabled)
    mock_settings = MagicMock()
    mock_settings.retrieval.rerank.enabled = True

    with (
        patch("rag.retriever.hybrid_search", return_value=mock_results),
        patch("rag.reranker.rerank_async", return_value=(mock_results[:2], "jina", False)),
        patch("config.settings.get_settings", return_value=mock_settings),
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
    assert data["meta"]["reranked"] is True
    assert data["meta"]["rerank_provider"] == "jina"


def test_search_empty_kb_ids(client):
    resp = client.post(
        "/api/search",
        json={"query": "테스트", "kb_ids": []},
    )
    assert resp.status_code == 422


def test_health_liveness(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}