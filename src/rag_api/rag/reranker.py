"""reranker.py — Jina/Cohere/Voyage 리랭커 + fallback(RRF 스코어 순)."""

from __future__ import annotations

import logging

import httpx

from rag_api.config.settings import get_settings
from rag_api.rag.retriever import SearchResult

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 리랭커 엔진
# ──────────────────────────────────────────────

async def _rerank_jina(
    query: str,
    results: list[SearchResult],
    top_n: int,
    api_key: str,
    model: str,
    timeout_sec: int,
) -> list[SearchResult]:
    url = "https://api.jina.ai/v1/rerank"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "query": query,
        "documents": [r.text for r in results],
        "top_n": top_n,
    }

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    reranked: list[SearchResult] = []
    for item in data.get("results", []):
        idx = item["index"]
        rerank_score = item["relevance_score"]
        result = results[idx]
        result.rerank_score = round(rerank_score, 6)
        reranked.append(result)

    return reranked


def _fallback(results: list[SearchResult], top_n: int) -> list[SearchResult]:
    """Reranker 실패 시 RRF 스코어 기준 상위 top_n 반환."""
    sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
    return sorted_results[:top_n]


# ──────────────────────────────────────────────
# 공개 인터페이스
# ──────────────────────────────────────────────

async def rerank_async(
    query: str,
    results: list[SearchResult],
    top_n: int | None = None,
) -> tuple[list[SearchResult], str, bool]:
    """
    Returns:
        (reranked_results, provider_used, fallback_used)
    """
    cfg = get_settings().retrieval.rerank

    if not cfg.enabled or not results:
        top = results[: top_n or cfg.top_n]
        return top, "none", False

    _top_n = top_n or cfg.top_n

    try:
        if cfg.provider == "jina":
            reranked = await _rerank_jina(
                query=query,
                results=results,
                top_n=_top_n,
                api_key=cfg.api_key,
                model=cfg.model,
                timeout_sec=cfg.timeout_sec,
            )
            return reranked, "jina", False

        else:
            raise NotImplementedError(f"provider={cfg.provider} 미지원")

    except Exception as e:
        logger.warning("Reranker failed (provider=%s), applying fallback: %s", cfg.provider, e)
        if cfg.fallback_on_error:
            return _fallback(results, _top_n), cfg.provider, True
        raise


def rerank(
    query: str,
    results: list[SearchResult],
    top_n: int | None = None,
) -> tuple[list[SearchResult], str, bool]:
    """동기 래퍼."""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(rerank_async(query, results, top_n))