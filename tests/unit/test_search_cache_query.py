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
        cfg = _cfg(enabled=True, match_mode="exact")

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
        cfg = _cfg(enabled=True, match_mode="exact")

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
        cfg = _cfg(enabled=True, match_mode="semantic", semantic_threshold=0.95)
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
        cfg = _cfg(enabled=True, match_mode="semantic", semantic_threshold=0.95)
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
        cfg = _cfg(enabled=True, match_mode="exact")

        with patch.object(search_cache.infra_cache, "set_entry") as mock_set_entry:
            search_cache.store(
                "hello", ["kb-a"], options, cfg, {"query": "hello"}, query_embedding=[0.1, 0.2],
            )

        payload = mock_set_entry.call_args.args[2]
        assert payload["query_embedding"] is None


class TestCacheGate:
    """set_cache_gate/_cache_usable 게이트 판단 로직 (US-55)."""

    def setup_method(self) -> None:
        search_cache.set_cache_gate(None)

    def teardown_method(self) -> None:
        search_cache.set_cache_gate(None)

    def _options(self) -> dict:
        return {
            "mode": "hybrid", "top_k": 10, "hybrid_alpha": 0.5,
            "hybrid_merge_strategy": "rrf", "min_score": 0.0,
            "rerank_enabled": True, "rerank_top_n": 3,
        }

    # AC: F1-1 (US-55-search-cache-gate-hook/T1)
    def test_no_hook_registered_lookup_uses_cache_cfg_only(self) -> None:
        """훅 미등록 상태에서 cfg.enabled=True면 기존과 동일하게 infra_cache를 조회한다."""
        cfg = _cfg(enabled=True, match_mode="exact")

        with patch.object(
            search_cache.infra_cache, "get_entry", return_value={"response": {"query": "hello"}},
        ) as mock_get_entry:
            response, _ = search_cache.lookup("hello", ["kb-a"], self._options(), cfg)

        mock_get_entry.assert_called_once()
        assert response == {"query": "hello"}

    # AC: F1-1 (US-55-search-cache-gate-hook/T1)
    def test_no_hook_registered_store_uses_cache_cfg_only(self) -> None:
        """훅 미등록 상태에서 cfg.enabled=True면 기존과 동일하게 infra_cache에 저장한다."""
        cfg = _cfg(enabled=True)

        with patch.object(search_cache.infra_cache, "set_entry") as mock_set_entry:
            search_cache.store("hello", ["kb-a"], self._options(), cfg, {"query": "hello"})

        mock_set_entry.assert_called_once()

    # AC: F1-2 (US-55-search-cache-gate-hook/T1)
    def test_hook_returns_false_blocks_lookup_even_if_enabled(self) -> None:
        """훅이 False를 반환하면 cfg.enabled=True여도 lookup이 (None, None)을 반환하고 조회하지 않는다."""
        search_cache.set_cache_gate(lambda kb_ids: False)
        cfg = _cfg(enabled=True, match_mode="exact")

        with patch.object(search_cache.infra_cache, "get_entry") as mock_get_entry:
            response, embedding = search_cache.lookup("hello", ["kb-a"], self._options(), cfg)

        mock_get_entry.assert_not_called()
        assert (response, embedding) == (None, None)

    # AC: F1-2 (US-55-search-cache-gate-hook/T1)
    def test_hook_returns_false_blocks_store_even_if_enabled(self) -> None:
        """훅이 False를 반환하면 cfg.enabled=True여도 store가 저장을 건너뛴다."""
        search_cache.set_cache_gate(lambda kb_ids: False)
        cfg = _cfg(enabled=True)

        with patch.object(search_cache.infra_cache, "set_entry") as mock_set_entry:
            search_cache.store("hello", ["kb-a"], self._options(), cfg, {"query": "hello"})

        mock_set_entry.assert_not_called()

    # AC: F1-3 (US-55-search-cache-gate-hook/T1)
    def test_hook_returns_true_behaves_like_no_hook(self) -> None:
        """훅이 True를 반환하고 cfg.enabled=True면 훅 미등록 때와 동일하게 조회가 발생한다."""
        search_cache.set_cache_gate(lambda kb_ids: True)
        cfg = _cfg(enabled=True, match_mode="exact")

        with patch.object(
            search_cache.infra_cache, "get_entry", return_value={"response": {"query": "hello"}},
        ) as mock_get_entry:
            response, _ = search_cache.lookup("hello", ["kb-a"], self._options(), cfg)

        mock_get_entry.assert_called_once()
        assert response == {"query": "hello"}

    # AC: F1-4 (US-55-search-cache-gate-hook/T1)
    def test_unregistering_hook_restores_no_hook_behavior(self) -> None:
        """훅을 None으로 해제하면 이후 요청은 F1-1과 동일(cfg.enabled만 보는) 동작으로 돌아온다."""
        search_cache.set_cache_gate(lambda kb_ids: False)
        search_cache.set_cache_gate(None)
        cfg = _cfg(enabled=True, match_mode="exact")

        with patch.object(
            search_cache.infra_cache, "get_entry", return_value={"response": {"query": "hello"}},
        ) as mock_get_entry:
            response, _ = search_cache.lookup("hello", ["kb-a"], self._options(), cfg)

        mock_get_entry.assert_called_once()
        assert response == {"query": "hello"}

    # AC: F1-2 (US-55-search-cache-gate-hook/T1)
    def test_hook_exception_falls_open_on_lookup(self) -> None:
        """훅이 예외를 던지면 기존 except Exception 블록에 흡수돼 (None, None)으로 폴백한다."""
        def _raising_hook(kb_ids: list[str]) -> bool:
            raise RuntimeError("boom")

        search_cache.set_cache_gate(_raising_hook)
        cfg = _cfg(enabled=True, match_mode="exact")

        response, embedding = search_cache.lookup("hello", ["kb-a"], self._options(), cfg)

        assert (response, embedding) == (None, None)

    # AC: F1-2 (US-55-search-cache-gate-hook/T1)
    def test_hook_exception_swallowed_on_store(self) -> None:
        """훅이 예외를 던져도 store는 예외를 흡수하고 저장을 건너뛴다."""
        def _raising_hook(kb_ids: list[str]) -> bool:
            raise RuntimeError("boom")

        search_cache.set_cache_gate(_raising_hook)
        cfg = _cfg(enabled=True)

        with patch.object(search_cache.infra_cache, "set_entry") as mock_set_entry:
            search_cache.store("hello", ["kb-a"], self._options(), cfg, {"query": "hello"})

        mock_set_entry.assert_not_called()

    # AC: F2-1 (US-55-search-cache-gate-hook/T1)
    @pytest.mark.parametrize("enabled,hook_result", [
        (True, None), (True, True), (True, False), (False, None), (False, True), (False, False),
    ])
    def test_cache_usable_matches_across_lookup_and_store_paths(
        self, enabled: bool, hook_result: bool | None,
    ) -> None:
        """동일한 (kb_ids, cfg.enabled, 훅) 조합에서 lookup/store가 동일한 게이트 판단을 따른다."""
        if hook_result is None:
            search_cache.set_cache_gate(None)
        else:
            fixed_result: bool = hook_result

            def _hook(kb_ids: list[str]) -> bool:
                return fixed_result

            search_cache.set_cache_gate(_hook)
        cfg = _cfg(enabled=enabled, match_mode="exact")
        expected_usable = search_cache._cache_usable(["kb-a"], cfg)

        with (
            patch.object(search_cache.infra_cache, "get_entry", return_value=None) as mock_get_entry,
            patch.object(search_cache.infra_cache, "set_entry") as mock_set_entry,
        ):
            search_cache.lookup("hello", ["kb-a"], self._options(), cfg)
            search_cache.store("hello", ["kb-a"], self._options(), cfg, {"query": "hello"})

        assert mock_get_entry.called == expected_usable
        assert mock_set_entry.called == expected_usable


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
