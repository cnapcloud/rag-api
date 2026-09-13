"""DELETE /api/search/cache — 캐시 수동 클리어 API 통합 테스트 (US-53 F5)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rag_api.api.app import create_app


@pytest.fixture
def client():
    with patch("rag_api.api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


class TestClearSpecificKb:
    # AC: F5-1 (US-53-search-cache/T6)
    def test_clear_kb_returns_cleared_count(self, client):
        """kb_id를 지정해 클리어하면 해당 kb의 캐시만 지우고 삭제 개수를 반환한다."""
        with patch("rag_api.query.search_cache.invalidate_kb", return_value=2) as mock_invalidate:
            resp = client.delete("/api/search/cache", params={"kb_id": "kb-a"})

        assert resp.status_code == 200
        assert resp.json() == {"status": "cleared", "kb_id": "kb-a", "cleared_count": 2}
        mock_invalidate.assert_called_once_with("kb-a")


class TestClearAll:
    # AC: F5-2 (US-53-search-cache/T6)
    def test_clear_all_returns_cleared_count(self, client):
        """kb_id 없이 호출하면 전체 검색 캐시를 지우고 삭제 개수를 반환한다."""
        with patch("rag_api.query.search_cache.invalidate_all", return_value=5) as mock_invalidate:
            resp = client.delete("/api/search/cache")

        assert resp.status_code == 200
        assert resp.json() == {"status": "cleared", "kb_id": None, "cleared_count": 5}
        mock_invalidate.assert_called_once()


class TestClearEmptyOrDisabledCache:
    # AC: F5-3 (US-53-search-cache/T6)
    def test_clear_kb_on_empty_cache_returns_zero(self, client):
        """캐시가 비어 있어도 kb_id 클리어 호출은 200과 cleared_count=0을 반환한다."""
        with patch("rag_api.query.search_cache.invalidate_kb", return_value=0):
            resp = client.delete("/api/search/cache", params={"kb_id": "nonexistent"})

        assert resp.status_code == 200
        assert resp.json()["cleared_count"] == 0

    # AC: F5-3 (US-53-search-cache/T6)
    def test_clear_all_on_empty_cache_returns_zero(self, client):
        """캐시가 비어 있어도 전체 클리어 호출은 200과 cleared_count=0을 반환한다."""
        with patch("rag_api.query.search_cache.invalidate_all", return_value=0):
            resp = client.delete("/api/search/cache")

        assert resp.status_code == 200
        assert resp.json()["cleared_count"] == 0


class TestClearRedisFailurePropagates:
    def test_redis_error_returns_503(self, client):
        """F5는 운영자가 명시적으로 호출하는 API이므로 Redis 장애를 삼키지 않는다(design.md 에러 모델)."""
        import redis as redis_lib

        with patch(
            "rag_api.query.search_cache.invalidate_kb",
            side_effect=redis_lib.RedisError("connection refused"),
        ):
            resp = client.delete("/api/search/cache", params={"kb_id": "kb-a"})

        assert resp.status_code == 503


class TestClearEndToEnd:
    def test_clear_kb_flips_previous_hit_to_miss(self, client, mock_redis):
        """F5-1 e2e: 클리어 후 이전에 hit이던 요청이 miss로 바뀐다."""
        from unittest.mock import AsyncMock, MagicMock

        from rag_api.infra import redis as redis_infra

        mock_settings = MagicMock()
        mock_settings.retrieval.mode = "hybrid"
        mock_settings.retrieval.top_k = 10
        mock_settings.retrieval.hybrid.alpha = 0.5
        mock_settings.retrieval.rerank.enabled = False
        mock_settings.retrieval.rerank.top_n = 3
        mock_settings.retrieval.similarity.min_score = 0.0
        mock_settings.retrieval.cache.enabled = True
        mock_settings.retrieval.cache.match_mode = "exact"
        mock_settings.retrieval.cache.ttl_seconds = 3600
        mock_settings.retrieval.cache.max_entries = 1000

        with (
            patch.object(redis_infra, "get_redis_client", return_value=mock_redis),
            patch("rag_api.config.settings.get_settings", return_value=mock_settings),
            patch(
                "rag_api.query.retriever.query",
                new=AsyncMock(return_value=([], 0, "none", False)),
            ),
        ):
            first = client.post("/api/search", json={"query": "q1", "kb_ids": ["kb-a"]})
            assert first.json()["meta"]["cache_status"] == "miss"

            second = client.post("/api/search", json={"query": "q1", "kb_ids": ["kb-a"]})
            assert second.json()["meta"]["cache_status"] == "hit"

            clear_resp = client.delete("/api/search/cache", params={"kb_id": "kb-a"})
            assert clear_resp.status_code == 200
            assert clear_resp.json()["cleared_count"] >= 1

            third = client.post("/api/search", json={"query": "q1", "kb_ids": ["kb-a"]})
            assert third.json()["meta"]["cache_status"] == "miss"
