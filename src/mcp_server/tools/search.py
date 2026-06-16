"""MCP tool: search."""

from __future__ import annotations

import time
from typing import Any

from mcp.server.fastmcp import Context
from opentelemetry import trace

from config.settings import get_settings
from rag.reranker import rerank_async
from rag.retriever import hybrid_search
from tracing.span import traced_tool


@traced_tool
async def search(
    query: str,
    kb_ids: list[str] | None = None,
    top_k: int | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Search knowledge bases using hybrid semantic + keyword search.

    If kb_ids is not specified, searches across all available knowledge bases.
    Returns ranked text chunks with source attribution (kb_id, doc_key, page_num).
    top_k controls the number of results returned (defaults to settings.retrieval.top_k).
    """
    span = trace.get_current_span()
    span.set_attribute("rag.query", query)

    cfg = get_settings()
    resolved_kb_ids = kb_ids or [kb.id for kb in cfg.knowledge_bases]
    if not resolved_kb_ids:
        return {"results": [], "latency_ms": 0}

    if kb_ids:
        span.set_attribute("rag.kb_ids", ",".join(kb_ids))

    start = time.monotonic()

    candidates = await hybrid_search(query=query, kb_ids=resolved_kb_ids, top_k=top_k)

    if candidates:
        final_results, _, _ = await rerank_async(query=query, results=candidates)
    else:
        final_results = candidates

    latency_ms = int((time.monotonic() - start) * 1000)
    span.set_attribute("rag.result_count", len(final_results))
    span.set_attribute("rag.latency_ms", latency_ms)

    return {
        "results": [
            {
                "text": r.text,
                "score": round(r.score, 6),
                "rerank_score": round(r.rerank_score, 6) if r.rerank_score is not None else None,
                "kb_id": r.kb_id,
                "doc_key": r.doc_key,
                "page_num": r.page_num,
                "chunk_idx": r.chunk_index,
            }
            for r in final_results
        ],
        "latency_ms": latency_ms,
    }
