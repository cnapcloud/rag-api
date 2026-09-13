"""infra/search_cache.py 단위 테스트 — 키/TTL/eviction/네임스페이스 (US-53)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rag_api.infra import search_cache
from rag_api.pipeline.queue.enqueue import (
    DELETE_QUEUE_KEY,
    UPLOAD_DELAY_KEY,
    UPLOAD_QUEUE_KEY,
)


@pytest.fixture
def patched_redis(mock_redis):
    with patch("rag_api.infra.redis.get_redis_client", return_value=mock_redis):
        yield mock_redis


def _payload(query: str, kb_ids: list[str]) -> dict:
    return {"query": query, "kb_ids": kb_ids, "response": {"query": query}, "query_embedding": None}


class TestSetAndGetEntry:
    def test_get_entry_missing_returns_none(self, patched_redis) -> None:
        assert search_cache.get_entry("bucket1", "query1") is None

    def test_set_then_get_entry_roundtrips(self, patched_redis) -> None:
        search_cache.set_entry(
            "bucket1", "query1", _payload("hello", ["kb-a"]), ["kb-a"],
            ttl_seconds=3600, max_entries=10,
        )

        entry = search_cache.get_entry("bucket1", "query1")

        assert entry is not None
        assert entry["query"] == "hello"
        assert entry["kb_ids"] == ["kb-a"]


class TestTtlExpiry:
    def test_entry_expires_after_ttl(self, patched_redis) -> None:
        """F1-3: TTL 경과(강제 만료) 후 엔트리 조회 시 None."""
        search_cache.set_entry(
            "bucket1", "query1", _payload("hello", ["kb-a"]), ["kb-a"],
            ttl_seconds=1, max_entries=10,
        )
        assert search_cache.get_entry("bucket1", "query1") is not None

        patched_redis.force_expire(search_cache._entry_key("bucket1", "query1"))

        assert search_cache.get_entry("bucket1", "query1") is None

    def test_set_entry_uses_configured_ttl(self, patched_redis) -> None:
        """F1-3: entry 저장 시 ttl_seconds가 그대로 TTL로 전달됨을 스파이로 확인."""
        with patch.object(patched_redis, "set", wraps=patched_redis.set) as spy:
            search_cache.set_entry(
                "bucket1", "query1", _payload("hello", ["kb-a"]), ["kb-a"],
                ttl_seconds=42, max_entries=10,
            )

        assert spy.call_args.kwargs["ex"] == 42


class TestEviction:
    def test_eviction_removes_oldest_when_over_max_entries(self, patched_redis) -> None:
        """F1-4: max_entries=2로 3개 저장 시 가장 오래된 것이 제거된다."""
        search_cache.set_entry("bucketA", "q1", _payload("q1", ["kb-a"]), ["kb-a"], ttl_seconds=3600, max_entries=2)
        search_cache.set_entry("bucketA", "q2", _payload("q2", ["kb-a"]), ["kb-a"], ttl_seconds=3600, max_entries=2)
        search_cache.set_entry("bucketA", "q3", _payload("q3", ["kb-a"]), ["kb-a"], ttl_seconds=3600, max_entries=2)

        assert search_cache.get_entry("bucketA", "q1") is None
        assert search_cache.get_entry("bucketA", "q2") is not None
        assert search_cache.get_entry("bucketA", "q3") is not None


class TestNamespaceSeparation:
    def test_cache_key_prefixes_do_not_collide_with_queue_keys(self, patched_redis) -> None:
        """F2-1: 캐시 키 prefix가 기존 큐 키 prefix(rag:upload:*, rag:delete:*)와 겹치지 않는다."""
        for prefix in (
            search_cache.ENTRY_PREFIX,
            search_cache.BUCKET_PREFIX,
            search_cache.KB_INDEX_PREFIX,
            search_cache.ORDER_KEY,
        ):
            assert not prefix.startswith("rag:upload:")
            assert not prefix.startswith("rag:delete:")

        assert not UPLOAD_QUEUE_KEY.startswith("rag:cache:")
        assert not DELETE_QUEUE_KEY.startswith("rag:cache:")
        assert not UPLOAD_DELAY_KEY.startswith("rag:cache:")


class TestInvalidation:
    def test_invalidate_kb_removes_matching_entries(self, patched_redis) -> None:
        search_cache.set_entry("bucketA", "q1", _payload("q1", ["kb-a"]), ["kb-a"], ttl_seconds=3600, max_entries=10)
        search_cache.set_entry("bucketB", "q2", _payload("q2", ["kb-b"]), ["kb-b"], ttl_seconds=3600, max_entries=10)

        cleared = search_cache.invalidate_kb("kb-a")

        assert cleared == 1
        assert search_cache.get_entry("bucketA", "q1") is None
        assert search_cache.get_entry("bucketB", "q2") is not None

    def test_invalidate_kb_missing_kb_returns_zero(self, patched_redis) -> None:
        assert search_cache.invalidate_kb("nonexistent") == 0

    def test_invalidate_all_clears_every_cache_key(self, patched_redis) -> None:
        search_cache.set_entry("bucketA", "q1", _payload("q1", ["kb-a"]), ["kb-a"], ttl_seconds=3600, max_entries=10)
        search_cache.set_entry("bucketB", "q2", _payload("q2", ["kb-b"]), ["kb-b"], ttl_seconds=3600, max_entries=10)

        cleared = search_cache.invalidate_all()

        assert cleared > 0
        assert search_cache.get_entry("bucketA", "q1") is None
        assert search_cache.get_entry("bucketB", "q2") is None

    def test_invalidate_all_on_empty_cache_returns_zero(self, patched_redis) -> None:
        assert search_cache.invalidate_all() == 0


class TestBucketQueryHashes:
    def test_get_bucket_query_hashes_returns_members(self, patched_redis) -> None:
        search_cache.set_entry("bucketA", "q1", _payload("q1", ["kb-a"]), ["kb-a"], ttl_seconds=3600, max_entries=10)
        search_cache.set_entry("bucketA", "q2", _payload("q2", ["kb-a"]), ["kb-a"], ttl_seconds=3600, max_entries=10)

        hashes = search_cache.get_bucket_query_hashes("bucketA")

        assert set(hashes) == {"q1", "q2"}
