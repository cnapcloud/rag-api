"""POST /api/search — Hybrid Search + Rerank."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from exceptions import IngestValidationError

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
    doc_key: str
    doc_source: str
    doc_type: str
    chunk_index: int
    page_num: Any | None
    text: str
    score: float
    rerank_score: float | None
    updated_at: str


class SearchMeta(BaseModel):
    total_candidates: int
    returned: int
    search_mode: str
    score_threshold: float
    reranked: bool
    rerank_provider: str
    rerank_fallback: bool
    latency_ms: int


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem]
    meta: SearchMeta


# ──────────────────────────────────────────────
# 엔드포인트
# ──────────────────────────────────────────────

@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    from config.settings import get_settings
    from rag.reranker import rerank_async
    from rag.retriever import search as retriever_search

    cfg = get_settings().retrieval

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

    # 1. Search (hybrid or similarity)
    candidates = await retriever_search(
        query=req.query,
        kb_ids=req.kb_ids,
        top_k=_top_k,
        alpha=_alpha,
        mode=_mode,
        min_score=_min_score,
    )
    total_candidates = len(candidates)

    # 2. Rerank
    rerank_enabled = req.options.rerank.enabled and cfg.rerank.enabled
    rerank_provider = cfg.rerank.provider if rerank_enabled else "none"
    fallback_used = False

    if rerank_enabled and candidates:
        _top_n = min(_top_n, len(candidates))
        final_results, rerank_provider, fallback_used = await rerank_async(
            query=req.query,
            results=candidates,
            top_n=_top_n,
        )
    else:
        final_results = candidates[:_top_k]

    latency_ms = int((time.monotonic() - start) * 1000)

    return SearchResponse(
        query=req.query,
        results=[
            SearchResultItem(
                chunk_id=r.chunk_id,
                kb_id=r.kb_id,
                doc_key=r.doc_key,
                doc_source=r.doc_source,
                doc_type=r.doc_type,
                chunk_index=r.chunk_index,
                page_num=r.page_num,
                text=r.text,
                score=r.score,
                rerank_score=r.rerank_score,
                updated_at=r.updated_at,
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
        ),
    )
