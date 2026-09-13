"""query/search_cache.py 단위 테스트 — 캐시 키 산출 + exact/semantic 판정 (US-53)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rag_api.config.settings import CacheSettings
from rag_api.query import search_cache


def _cfg(**overrides) -> CacheSettings:
    return CacheSettings(**overrides)


class TestBucketHash:
    # AC: F3-1 (US-53-search-cache/T3)
    def test_different_option_value_yields_different_bucket_hash(self) -> None:
        """옵션 값 하나만 달라도 다른 bucket_hash가 나온다."""
        base = {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }
        other = {**base, "top_k": 20}

        assert search_cache.build_bucket_hash(["kb-a"], base) != search_cache.build_bucket_hash(
            ["kb-a"], other,
        )

    # AC: F3-1 (US-53-search-cache/T3)
    def test_same_options_and_kb_ids_yield_same_bucket_hash(self) -> None:
        """동일 옵션 + 동일 kb_ids면 동일 bucket_hash가 나온다."""
        options = {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }

        assert search_cache.build_bucket_hash(["kb-a"], options) == search_cache.build_bucket_hash(
            ["kb-a"], dict(options),
        )

    # AC: F3-2 (US-53-search-cache/T3)
    def test_kb_ids_order_does_not_affect_bucket_hash(self) -> None:
        """kb_ids 순서만 다르면 동일 bucket_hash를 공유한다."""
        options = {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }

        assert search_cache.build_bucket_hash(
            ["kb-a", "kb-b"], options,
        ) == search_cache.build_bucket_hash(["kb-b", "kb-a"], options)


class TestCosineSimilarity:
    def test_identical_vectors_similarity_is_one(self) -> None:
        """동일 벡터의 코사인 유사도는 1이다."""
        assert search_cache.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_similarity_is_zero(self) -> None:
        """직교 벡터의 코사인 유사도는 0이다."""
        assert search_cache.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_zero_vector_returns_zero_without_raising(self) -> None:
        """영벡터가 입력돼도 예외 없이 0을 반환한다."""
        assert search_cache.cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


class TestLookupExactMode:
    def test_exact_mode_hit_returns_response_without_embedding(self) -> None:
        """exact 모드에서 캐시 hit이면 임베딩 계산 없이 저장된 응답을 그대로 반환한다."""
        options = {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }
        cfg = _cfg(match_mode="exact")

        with patch.object(
            search_cache.infra_cache, "get_entry", return_value={"response": {"query": "hello"}},
        ):
            response, embedding = search_cache.lookup("hello", ["kb-a"], options, cfg)

        assert response == {"query": "hello"}
        assert embedding is None

    # AC: F3-6 (US-53-search-cache/T3)
    def test_exact_mode_never_computes_embedding(self) -> None:
        """exact 모드에서는 유사도 비교 로직이 전혀 실행되지 않는다."""
        options = {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }
        cfg = _cfg(match_mode="exact")

        with (
            patch.object(search_cache.infra_cache, "get_entry", return_value=None),
            patch("rag_api.pipeline.steps.embed.build_embed_model") as mock_build,
        ):
            response, embedding = search_cache.lookup("hello but different", ["kb-a"], options, cfg)

        assert response is None
        assert embedding is None
        mock_build.assert_not_called()


class TestLookupSemanticMode:
    def _options(self) -> dict:
        return {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }

    # AC: F3-5 (US-53-search-cache/T3)
    def test_similarity_above_threshold_is_hit(self) -> None:
        """유사도가 threshold 이상이면 semantic 캐시 hit을 반환한다."""
        cfg = _cfg(match_mode="semantic", semantic_threshold=0.95)
        query_embedding = [1.0, 0.0]
        # cosine([1,0],[0.96,0.28]) ~= 0.96 >= 0.95
        candidate_embedding = [0.96, 0.28]

        mock_model = MagicMock()
        mock_model.get_query_embedding.return_value = query_embedding

        with (
            patch("rag_api.pipeline.steps.embed.build_embed_model", return_value=mock_model),
            patch.object(search_cache.infra_cache, "get_entry") as mock_get_entry,
            patch.object(
                search_cache.infra_cache, "get_bucket_query_hashes", return_value=["qhash-1"],
            ),
        ):
            def _get_entry_side_effect(bucket_hash, query_hash):
                if query_hash == search_cache.build_query_hash(bucket_hash, "new query"):
                    return None
                return {
                    "response": {"query": "similar query"},
                    "query_embedding": candidate_embedding,
                }

            mock_get_entry.side_effect = _get_entry_side_effect

            response, embedding = search_cache.lookup("new query", ["kb-a"], self._options(), cfg)

        assert response == {"query": "similar query"}
        assert embedding == query_embedding

    # AC: F3-5 (US-53-search-cache/T3)
    def test_similarity_below_threshold_is_miss(self) -> None:
        """유사도가 threshold 미만이면 miss로 처리하고, 재사용할 질의 임베딩은 반환한다."""
        cfg = _cfg(match_mode="semantic", semantic_threshold=0.95)
        query_embedding = [1.0, 0.0]
        # cosine([1,0],[0.5,0.87]) ~= 0.5 < 0.95
        candidate_embedding = [0.5, 0.87]

        mock_model = MagicMock()
        mock_model.get_query_embedding.return_value = query_embedding

        with (
            patch("rag_api.pipeline.steps.embed.build_embed_model", return_value=mock_model),
            patch.object(search_cache.infra_cache, "get_entry") as mock_get_entry,
            patch.object(
                search_cache.infra_cache, "get_bucket_query_hashes", return_value=["qhash-1"],
            ),
        ):
            def _get_entry_side_effect(bucket_hash, query_hash):
                if query_hash == search_cache.build_query_hash(bucket_hash, "new query"):
                    return None
                return {
                    "response": {"query": "unrelated query"},
                    "query_embedding": candidate_embedding,
                }

            mock_get_entry.side_effect = _get_entry_side_effect

            response, embedding = search_cache.lookup("new query", ["kb-a"], self._options(), cfg)

        assert response is None
        assert embedding == query_embedding


class TestLookupFailOpen:
    def test_redis_error_falls_back_to_miss(self) -> None:
        """Redis 오류가 나면 예외를 삼키고 miss로 폴백한다(fail-open)."""
        options = {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }
        cfg = _cfg(match_mode="exact")

        with patch.object(search_cache.infra_cache, "get_entry", side_effect=RuntimeError("boom")):
            response, embedding = search_cache.lookup("hello", ["kb-a"], options, cfg)

        assert response is None
        assert embedding is None


class TestStore:
    def test_store_swallows_infra_errors(self) -> None:
        """저장 중 Redis 오류가 나도 예외를 삼키고 검색 응답 경로를 막지 않는다."""
        options = {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }
        cfg = _cfg()

        with patch.object(search_cache.infra_cache, "set_entry", side_effect=RuntimeError("boom")):
            search_cache.store("hello", ["kb-a"], options, cfg, {"query": "hello"})  # should not raise

    def test_store_omits_embedding_when_exact_mode(self) -> None:
        """exact 모드에서는 저장 payload에 query_embedding을 채우지 않는다."""
        options = {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }
        cfg = _cfg(match_mode="exact")

        with patch.object(search_cache.infra_cache, "set_entry") as mock_set_entry:
            search_cache.store(
                "hello", ["kb-a"], options, cfg, {"query": "hello"}, query_embedding=[0.1, 0.2],
            )

        payload = mock_set_entry.call_args.args[2]
        assert payload["query_embedding"] is None


class TestInvalidation:
    def test_invalidate_kb_best_effort_swallows_exception(self) -> None:
        """best-effort 버전은 infra 오류를 삼키고 0을 반환한다."""
        with patch.object(search_cache.infra_cache, "invalidate_kb", side_effect=RuntimeError("boom")):
            assert search_cache.invalidate_kb_best_effort("kb-a") == 0

    def test_invalidate_kb_best_effort_returns_count_on_success(self) -> None:
        """best-effort 버전은 성공 시 infra 계층의 삭제 개수를 그대로 반환한다."""
        with patch.object(search_cache.infra_cache, "invalidate_kb", return_value=3):
            assert search_cache.invalidate_kb_best_effort("kb-a") == 3

    def test_invalidate_kb_propagates_exception(self) -> None:
        """raw 버전(F5용)은 infra 오류를 흡수하지 않고 그대로 전파한다."""
        with (
            patch.object(search_cache.infra_cache, "invalidate_kb", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            search_cache.invalidate_kb("kb-a")
