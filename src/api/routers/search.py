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
    title: str
    source_type: str
    source: str
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

    rerank_enabled = req.options.rerank.enabled and cfg.rerank.enabled

    final_results, total_candidates, rerank_provider, fallback_used = await retriever_search(
        query=req.query,
        kb_ids=req.kb_ids,
        top_k=_top_k,
        alpha=_alpha,
        mode=_mode,
        min_score=_min_score,
        rerank_enabled=rerank_enabled,
        top_n=_top_n,
    )

    latency_ms = int((time.monotonic() - start) * 1000)

    return SearchResponse(
        query=req.query,
        results=[
            SearchResultItem(
                chunk_id=r.chunk_id,
                kb_id=r.kb_id,
                doc_key=r.doc_key,
                title=r.title,
                source_type=r.source_type,
                source=r.source,
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
