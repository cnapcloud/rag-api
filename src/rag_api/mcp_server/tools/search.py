"""MCP tool: search."""

from __future__ import annotations

import time
from typing import Any, Literal

from mcp.server.fastmcp import Context
from opentelemetry import trace

from rag_api.config.settings import get_settings
from rag_api.rag.retriever import search as retriever_search
from rag_api.tracing.span import traced_tool


@traced_tool
async def search(
    query: str,
    kb_ids: list[str] | None = None,
    top_k: int | None = None,
    mode: Literal["hybrid", "similarity"] | None = None,
    min_score: float | None = None,
    ctx: Context | None = None,
) -> dict[str, Any]:
    """Search knowledge bases and return relevant text chunks.

    kb_ids: knowledge base IDs to search. Omit to search all available KBs.
    top_k: maximum number of results to return. Defaults to server setting.
    mode: 'hybrid' for keyword+semantic search (better for specific terms),
          'similarity' for semantic-only search (better for conceptual queries).
          Defaults to server setting.
    min_score: minimum similarity score threshold (0.0~1.0), applies only in
               'similarity' mode. Omit to use server default.
    """
    span = trace.get_current_span()
    span.set_attribute("rag.query", query)

    cfg = get_settings()
    resolved_kb_ids = kb_ids or [kb.id for kb in cfg.knowledge_bases]
    if not resolved_kb_ids:
        return {"results": [], "latency_ms": 0}

    if kb_ids:
        span.set_attribute("rag.kb_ids", ",".join(kb_ids))

    _mode = mode if mode is not None else cfg.retrieval.mode
    _min_score = min_score if min_score is not None else cfg.retrieval.similarity.min_score
    start = time.monotonic()

    final_results, _, _, _ = await retriever_search(
        query=query, kb_ids=resolved_kb_ids, top_k=top_k, mode=_mode, min_score=_min_score
    )

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
