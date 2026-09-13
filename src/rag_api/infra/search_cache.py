"""Redis 검색 캐시 primitive — 키 스킴/CRUD/eviction/무효화 (US-53).

Redis I/O만 여기에 둔다 — 캐시 키 산출·시맨틱 유사도 비교 같은 검색 도메인 로직은
`query/search_cache.py`에 있다 (docs/internal/design/data-schema.md §3, design.md 참고).

기존 인제스트/삭제 큐 키(`rag:upload:*`, `rag:delete:*`, `pipeline/queue/enqueue.py`)와
겹치지 않도록 별도 prefix(`rag:cache:*`)를 쓴다 — 같은 Redis DB index를 재사용한다.

여기의 함수들은 라이브러리 예외(`redis.RedisError` 등)를 감싸지 않고 그대로 propagate한다
(exception-handling 스킬 — infra 레이어 규칙). 호출부(`query/search_cache.py`)가 정책에 따라
흡수하거나 전파한다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

ENTRY_PREFIX = "rag:cache:entry"
BUCKET_PREFIX = "rag:cache:bucket"
KB_INDEX_PREFIX = "rag:cache:kb"
ORDER_KEY = "rag:cache:order"


def _entry_key(bucket_hash: str, query_hash: str) -> str:
    return f"{ENTRY_PREFIX}:{bucket_hash}:{query_hash}"


def _bucket_key(bucket_hash: str) -> str:
    return f"{BUCKET_PREFIX}:{bucket_hash}"


def _kb_index_key(kb_id: str) -> str:
    return f"{KB_INDEX_PREFIX}:{kb_id}"


def _full_key(bucket_hash: str, query_hash: str) -> str:
    return f"{bucket_hash}:{query_hash}"


def get_entry(bucket_hash: str, query_hash: str) -> dict[str, Any] | None:
    """캐시 엔트리를 조회한다. 없거나 만료됐으면 None."""
    from rag_api.infra.redis import get_redis_client

    raw = get_redis_client().get(_entry_key(bucket_hash, query_hash))
    if raw is None:
        return None
    return json.loads(raw)


def set_entry(
    bucket_hash: str,
    query_hash: str,
    payload: dict[str, Any],
    kb_ids: list[str],
    ttl_seconds: int,
    max_entries: int,
) -> None:
    """캐시 엔트리를 저장하고 bucket/kb/order 인덱스를 갱신한 뒤 상한 초과분을 정리한다."""
    from rag_api.infra.redis import get_redis_client

    client = get_redis_client()
    full_key = _full_key(bucket_hash, query_hash)

    client.set(_entry_key(bucket_hash, query_hash), json.dumps(payload), ex=ttl_seconds)

    bucket_key = _bucket_key(bucket_hash)
    client.sadd(bucket_key, query_hash)
    client.expire(bucket_key, ttl_seconds)

    for kb_id in kb_ids:
        kb_key = _kb_index_key(kb_id)
        client.sadd(kb_key, full_key)
        client.expire(kb_key, ttl_seconds)

    client.zadd(ORDER_KEY, {full_key: time.time()})

    evict_if_needed(max_entries)


def evict_if_needed(max_entries: int) -> None:
    """`rag:cache:order` 크기가 max_entries를 넘으면 FIFO로 가장 오래된 엔트리부터 정리한다.

    TTL로 이미 자연 만료된 엔트리를 만나면(entry GET이 None) 인덱스 정리 없이 order에서만
    제거하고 카운트를 줄인다 — design.md 리스크 2의 lazy cleanup 근사치.
    """
    from rag_api.infra.redis import get_redis_client

    client = get_redis_client()
    evicted = 0
    while client.zcard(ORDER_KEY) > max_entries:
        oldest = client.zrange(ORDER_KEY, 0, 0)
        if not oldest:
            break
        full_key = oldest[0]
        client.zrem(ORDER_KEY, full_key)

        bucket_hash, _, query_hash = full_key.partition(":")
        raw = client.get(_entry_key(bucket_hash, query_hash))
        if raw is not None:
            entry = json.loads(raw)
            client.delete(_entry_key(bucket_hash, query_hash))
            client.srem(_bucket_key(bucket_hash), query_hash)
            for kb_id in entry.get("kb_ids", []):
                client.srem(_kb_index_key(kb_id), full_key)
        evicted += 1

    if evicted:
        logger.info("Search cache evicted: count=%d max_entries=%d", evicted, max_entries)


def get_bucket_query_hashes(bucket_hash: str) -> list[str]:
    """시맨틱 매칭 스캔용 — 버킷에 속한 query_hash 목록."""
    from rag_api.infra.redis import get_redis_client

    return list(get_redis_client().smembers(_bucket_key(bucket_hash)))


def invalidate_kb(kb_id: str) -> int:
    """해당 kb_id가 포함된 캐시 엔트리를 모두 삭제한다. 삭제된 엔트리 수를 반환한다.

    예외를 흡수하지 않는다 — F5(수동 클리어 API)용 raw 버전.
    """
    from rag_api.infra.redis import get_redis_client

    client = get_redis_client()
    kb_key = _kb_index_key(kb_id)
    full_keys = client.smembers(kb_key)

    count = 0
    for full_key in full_keys:
        bucket_hash, _, query_hash = full_key.partition(":")
        raw = client.get(_entry_key(bucket_hash, query_hash))
        client.delete(_entry_key(bucket_hash, query_hash))
        client.srem(_bucket_key(bucket_hash), query_hash)
        client.zrem(ORDER_KEY, full_key)
        if raw is not None:
            count += 1

    client.delete(kb_key)
    return count


def invalidate_all() -> int:
    """`rag:cache:*` 전체를 삭제한다. 삭제된 키 개수를 반환한다.

    예외를 흡수하지 않는다 — F5(수동 클리어 API)용.
    """
    from rag_api.infra.redis import get_redis_client

    client = get_redis_client()
    keys = list(client.scan_iter(match="rag:cache:*"))
    count = 0
    for key in keys:
        count += client.delete(key)
    return count
