"""POST /api/search — Hybrid Search + Rerank. DELETE /api/search/cache — 검색 캐시 수동 클리어(US-53 F5)."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from rag_api.exceptions import IngestValidationError
from rag_api.tracing.span import rest_span

router = APIRouter()


# ──────────────────────────────────────────────
# 요청/응답 스키마
# ──────────────────────────────────────────────

class RerankOptions(BaseModel):
    enabled: bool = True
    top_n: int | None = None   # None → settings 값 사용


class HybridOptions(BaseModel):
    alpha: float | None = None   # None → settings 값 사용
    merge_strategy: str = "rrf"


class SimilarityOptions(BaseModel):
    min_score: float | None = None   # None → settings 값 사용


class SearchOptions(BaseModel):
    mode: Literal["hybrid", "similarity"] | None = None   # None → settings 값 사용
    top_k: int | None = None   # None → settings 값 사용
    hybrid: HybridOptions = Field(default_factory=HybridOptions)
    similarity: SimilarityOptions = Field(default_factory=SimilarityOptions)
    rerank: RerankOptions = Field(default_factory=RerankOptions)


class SearchRequest(BaseModel):
    query: str
    kb_ids: list[str]
    options: SearchOptions = Field(default_factory=SearchOptions)


class SearchResultItem(BaseModel):
    chunk_id: str
    kb_id: str
    doc_id: str
    title: str
    source_type: str
    source: str
    doc_type: str
    chunk_index: int | None
    page_num: Any | None
    page_label: str | None
    text: str
    score: float
    rerank_score: float | None
    updated_at: str
    merged: bool
    parent_chunk_id: str | None


class SearchMeta(BaseModel):
    total_candidates: int
    returned: int
    search_mode: str
    score_threshold: float
    reranked: bool
    rerank_provider: str
    rerank_fallback: bool
    latency_ms: int
    cache_status: Literal["hit", "miss", "disabled"]


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    meta: SearchMeta


# ──────────────────────────────────────────────
# 엔드포인트
# ──────────────────────────────────────────────

@router.post("/search", response_model=SearchResponse)
@rest_span
async def search(req: SearchRequest):
    from rag_api.config.settings import get_settings
    from rag_api.query import search_cache
    from rag_api.query.retriever import query as retriever_search

    settings = get_settings()
    cfg = settings.retrieval
    cache_cfg = settings.search_cache

    if not req.kb_ids:
        raise IngestValidationError("kb_ids must contain at least one entry.")

    # Priority: request option → settings → settings default
    _mode = req.options.mode if req.options.mode is not None else cfg.mode
    _top_k = req.options.top_k if req.options.top_k is not None else cfg.top_k
    _alpha = req.options.hybrid.alpha if req.options.hybrid.alpha is not None else cfg.hybrid.alpha
    _top_n = req.options.rerank.top_n if req.options.rerank.top_n is not None else cfg.rerank.top_n
    _min_score = (
        req.options.similarity.min_score
        if req.options.similarity.min_score is not None
        else cfg.similarity.min_score
    )

    start = time.monotonic()

    rerank_enabled = req.options.rerank.enabled and cfg.rerank.enabled

    effective_options = {
        "mode": _mode,
        "top_k": _top_k,
        "hybrid_alpha": _alpha,
        "hybrid_merge_strategy": req.options.hybrid.merge_strategy,
        "min_score": _min_score,
        "rerank_enabled": rerank_enabled,
        "rerank_top_n": _top_n,
    }

    query_embedding: list[float] | None = None
    if cache_cfg.enabled:
        cached, query_embedding = search_cache.lookup(
            req.query, req.kb_ids, effective_options, cache_cfg,
        )
        if cached is not None:
            cached["meta"]["cache_status"] = "hit"
            return SearchResponse(**cached)

    final_results, total_candidates, rerank_provider, fallback_used = await retriever_search(
        query=req.query,
        kb_ids=req.kb_ids,
        top_k=_top_k,
        alpha=_alpha,
        mode=_mode,
        min_score=_min_score,
        rerank_enabled=rerank_enabled,
        top_n=_top_n,
        query_embedding=query_embedding,
    )

    latency_ms = int((time.monotonic() - start) * 1000)

    response = SearchResponse(
        query=req.query,
        results=[
            SearchResultItem(
                chunk_id=r.chunk_id,
                kb_id=r.kb_id,
                doc_id=r.doc_id,
                title=r.title,
                source_type=r.source_type,
                source=r.source,
                doc_type=r.doc_type,
                chunk_index=r.chunk_index,
                page_num=r.page_num,
                page_label=r.page_label,
                text=r.text,
                score=r.score,
                rerank_score=r.rerank_score,
                updated_at=r.updated_at,
                merged=r.merged,
                parent_chunk_id=r.parent_chunk_id,
            )
            for r in final_results
        ],
        meta=SearchMeta(
            total_candidates=total_candidates,
            returned=len(final_results),
            search_mode=_mode,
            score_threshold=_min_score,
            reranked=rerank_enabled and not fallback_used,
            rerank_provider=rerank_provider,
            rerank_fallback=fallback_used,
            latency_ms=latency_ms,
            cache_status="miss" if cache_cfg.enabled else "disabled",
        ),
    )

    if cache_cfg.enabled:
        search_cache.store(
            req.query, req.kb_ids, effective_options, cache_cfg,
            response.model_dump(), query_embedding,
        )

    return response


@router.delete("/search/cache")
@rest_span
async def clear_search_cache(kb_id: str | None = Query(default=None)):
    """검색 캐시를 강제로 비운다(F5) — `kb_id` 지정 시 해당 KB만, 생략 시 전체.

    존재하지 않는 kb_id나 이미 비어 있는 캐시도 정상 200(F5-3)으로 처리한다. Redis 자체 장애는
    삼키지 않고 그대로 전파해 기존 `redis_lib.RedisError → 503` 전역 핸들러가 응답한다
    (design.md 에러 모델 — F5는 운영자가 명시적으로 호출하는 API라 실패를 숨기지 않는다).
    """
    from rag_api.query import search_cache

    if kb_id is not None:
        cleared = search_cache.invalidate_kb(kb_id)
    else:
        cleared = search_cache.invalidate_all()

    return {"status": "cleared", "kb_id": kb_id, "cleared_count": cleared}
