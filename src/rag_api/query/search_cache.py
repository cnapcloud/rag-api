"""검색 응답 캐시 — 도메인 로직 (US-53).

캐시 키(버킷/쿼리 해시) 산출, exact/semantic 판정, 저장, 무효화 오케스트레이션을 담당한다.
Redis I/O 자체는 `infra/search_cache.py`에 있다 (design.md 레이어 분리 원칙 참고).

검색 요청 경로(`lookup`/`store`)는 fail-open이다 — Redis 장애나 예기치 못한 역직렬화 오류를
내부에서 흡수하고 캐시 미스처럼 폴백한다(design.md 에러 모델). 반대로 F5 수동 클리어용
`invalidate_kb`/`invalidate_all`은 예외를 흡수하지 않고 그대로 전파하며, F4 자동 무효화 훅이
쓰는 `invalidate_kb_best_effort`만 별도로 예외를 흡수한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from rag_api.infra import search_cache as infra_cache

if TYPE_CHECKING:
    from rag_api.config.settings import SearchCacheSettings

logger = logging.getLogger(__name__)

_cache_gate: Callable[[list[str]], bool] | None = None


def set_cache_gate(fn: Callable[[list[str]], bool] | None) -> None:
    """캐시 게이트 훅을 등록/해제한다. `fn(kb_ids) -> bool`이 False를 반환하면 그 요청은
    `cache_cfg.enabled`와 무관하게 캐시 조회/저장을 모두 건너뛴다. `None`으로 호출하면
    훅을 해제하고 기존(cache_cfg.enabled만 보는) 동작으로 되돌린다."""
    global _cache_gate
    _cache_gate = fn


def _cache_usable(kb_ids: list[str], cfg: SearchCacheSettings) -> bool:
    """lookup/store가 공유하는 단일 판단 지점 (F2-1). cfg.enabled가 False면 그 자체로
    False. True인 경우에만 게이트 훅을 본다 — 훅이 없으면 그대로 True(F1-1)."""
    if not cfg.enabled:
        return False
    if _cache_gate is None:
        return True
    return _cache_gate(kb_ids)


def build_bucket_hash(kb_ids: list[str], effective_options: dict[str, Any]) -> str:
    """kb_ids(순서 무관, F3-2) + 검색 옵션 조합(F3-1) 전체를 식별하는 해시."""
    payload = {"kb_ids": sorted(kb_ids), **effective_options}
    serialized = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_query_hash(bucket_hash: str, query: str) -> str:
    """exact 매칭 키 — 버킷 + 질의 문자열 원문."""
    serialized = f"{bucket_hash}|{query}"
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """두 벡터의 코사인 유사도. 둘 중 하나라도 영벡터면 0.0."""
    if len(a) != len(b):
        raise ValueError(f"Vector length mismatch: {len(a)} != {len(b)}")

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _get_query_embedding(query: str) -> list[float]:
    """검색 파이프라인과 동일한 임베딩 모델로 질의 임베딩을 계산한다 (재사용, 재생성 금지)."""
    from rag_api.pipeline.steps.embed import build_embed_model

    return build_embed_model().get_query_embedding(query)


def lookup(
    query: str,
    kb_ids: list[str],
    effective_options: dict[str, Any],
    cfg: SearchCacheSettings,
) -> tuple[dict[str, Any] | None, list[float] | None]:
    """캐시 hit 시 (response, None), semantic miss로 임베딩만 계산했으면 (None, embedding),
    그 외 (None, None)을 반환한다.

    Redis 오류/역직렬화 오류는 내부에서 흡수해 캐시 미스처럼 폴백한다(fail-open).
    """
    try:
        if not _cache_usable(kb_ids, cfg):
            return None, None
        bucket_hash = build_bucket_hash(kb_ids, effective_options)
        query_hash = build_query_hash(bucket_hash, query)

        entry = infra_cache.get_entry(bucket_hash, query_hash)
        if entry is not None:
            logger.info("Search cache hit: mode=exact bucket=%s", bucket_hash[:8])
            return entry["response"], None

        if cfg.match_mode != "semantic":
            # F3-6: exact 모드에서는 시맨틱 유사도 비교 로직이 전혀 실행되지 않는다.
            logger.info("Search cache miss: mode=exact bucket=%s", bucket_hash[:8])
            return None, None

        embedding = _get_query_embedding(query)
        best_score = 0.0
        best_entry: dict[str, Any] | None = None
        for candidate_hash in infra_cache.get_bucket_query_hashes(bucket_hash):
            candidate = infra_cache.get_entry(bucket_hash, candidate_hash)
            if candidate is None or candidate.get("query_embedding") is None:
                continue
            score = cosine_similarity(embedding, candidate["query_embedding"])
            if score >= cfg.semantic_threshold and score > best_score:
                best_score = score
                best_entry = candidate

        if best_entry is not None:
            logger.info("Search cache hit: mode=semantic bucket=%s", bucket_hash[:8])
            return best_entry["response"], embedding

        logger.info("Search cache miss: mode=semantic bucket=%s", bucket_hash[:8])
        return None, embedding
    except Exception as e:
        logger.warning("Search cache lookup failed (fallback to real search): err=%s", e)
        return None, None


def store(
    query: str,
    kb_ids: list[str],
    effective_options: dict[str, Any],
    cfg: SearchCacheSettings,
    response_dict: dict[str, Any],
    query_embedding: list[float] | None = None,
) -> None:
    """검색 응답을 캐시에 저장한다. Redis 오류는 흡수한다(저장 실패가 응답을 막지 않음)."""
    try:
        if not _cache_usable(kb_ids, cfg):
            return
        bucket_hash = build_bucket_hash(kb_ids, effective_options)
        query_hash = build_query_hash(bucket_hash, query)

        payload = {
            "query": query,
            "kb_ids": sorted(kb_ids),
            "response": response_dict,
            "query_embedding": query_embedding if cfg.match_mode == "semantic" else None,
            "created_at": time.time(),
        }
        infra_cache.set_entry(
            bucket_hash, query_hash, payload, kb_ids,
            ttl_seconds=cfg.ttl_seconds, max_entries=cfg.max_entries,
        )
        logger.info("Search cache stored: bucket=%s ttl=%d", bucket_hash[:8], cfg.ttl_seconds)
    except Exception as e:
        logger.warning("Search cache store failed (ignored): err=%s", e)


def invalidate_kb(kb_id: str) -> int:
    """F5(수동 클리어) — raw, 예외를 흡수하지 않고 그대로 전파한다."""
    count = infra_cache.invalidate_kb(kb_id)
    logger.info("Search cache invalidated: kb_id=%s cleared=%d", kb_id, count)
    return count


def invalidate_all() -> int:
    """F5(수동 클리어) — raw, 예외를 흡수하지 않고 그대로 전파한다."""
    count = infra_cache.invalidate_all()
    logger.info("Search cache invalidated: kb_id=* cleared=%d", count)
    return count


def invalidate_kb_best_effort(kb_id: str) -> int:
    """F4(자동 무효화) — 예외를 흡수해 인제스트/삭제 완료 자체를 막지 않는다."""
    try:
        return invalidate_kb(kb_id)
    except Exception as e:
        logger.warning("Search cache invalidation failed (ignored): kb_id=%s err=%s", kb_id, e)
        return 0
