"""retriever.py — LlamaIndex VectorStoreIndex + Qdrant Hybrid / Similarity Search."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    chunk_id: str
    kb_id: str
    doc_key: str
    doc_type: str
    chunk_index: int
    page_num: int | None
    text: str
    score: float
    rerank_score: float | None
    updated_at: str


def _build_vector_store(kb_id: str, qdrant_client=None):
    from llama_index.vector_stores.qdrant import QdrantVectorStore

    from infra.qdrant import get_qdrant_client
    from pipeline.ops.sparse import compute_sparse_tf

    client = qdrant_client or get_qdrant_client()
    return QdrantVectorStore(
        client=client,
        collection_name=kb_id,
        enable_hybrid=True,
        sparse_doc_fn=compute_sparse_tf,
        sparse_query_fn=compute_sparse_tf,
        dense_vector_name="dense",
        sparse_vector_name="sparse",
    )


def _build_index(kb_id: str, embed_model=None):
    from llama_index.core import VectorStoreIndex

    from pipeline.ops.embed import build_embed_model

    vector_store = _build_vector_store(kb_id)
    em = embed_model or build_embed_model()
    return VectorStoreIndex.from_vector_store(vector_store, embed_model=em)


def search_hybrid_kb(
    kb_id: str,
    query: str,
    top_k: int | None = None,
    alpha: float | None = None,
) -> list[SearchResult]:
    """Single KB hybrid search (dense+sparse, RRF score)."""
    cfg = get_settings().retrieval
    _top_k = top_k or cfg.top_k
    _alpha = alpha if alpha is not None else cfg.hybrid.alpha

    index = _build_index(kb_id)
    retriever = index.as_retriever(
        similarity_top_k=_top_k,
        vector_store_query_mode="hybrid",
        alpha=_alpha,
    )

    nodes = retriever.retrieve(query)
    results: list[SearchResult] = []
    for node in nodes:
        meta = node.metadata
        results.append(
            SearchResult(
                chunk_id=node.node_id,
                kb_id=kb_id,
                doc_key=meta.get("doc_key", ""),
                doc_type=meta.get("doc_type", ""),
                chunk_index=int(meta.get("chunk_index", 0)),
                page_num=meta.get("page_num") or meta.get("page_label"),
                text=node.get_content(),
                score=float(node.score or 0.0),
                rerank_score=None,
                updated_at=meta.get("updated_at", ""),
            )
        )
    return results


def search_similarity_kb(
    kb_id: str,
    query: str,
    top_k: int | None = None,
    min_score: float = 0.0,
) -> list[SearchResult]:
    """Single KB dense-only search (cosine similarity score, 0.0~1.0)."""
    cfg = get_settings().retrieval
    _top_k = top_k or cfg.top_k

    index = _build_index(kb_id)
    retriever = index.as_retriever(
        similarity_top_k=_top_k,
        vector_store_query_mode="default",
    )

    nodes = retriever.retrieve(query)
    results: list[SearchResult] = []
    for node in nodes:
        score = float(node.score or 0.0)
        if score < min_score:
            continue
        meta = node.metadata
        results.append(
            SearchResult(
                chunk_id=node.node_id,
                kb_id=kb_id,
                doc_key=meta.get("doc_key", ""),
                doc_type=meta.get("doc_type", ""),
                chunk_index=int(meta.get("chunk_index", 0)),
                page_num=meta.get("page_num") or meta.get("page_label"),
                text=node.get_content(),
                score=score,
                rerank_score=None,
                updated_at=meta.get("updated_at", ""),
            )
        )
    return results


async def _search_hybrid_kb_async(
    kb_id: str, query: str, top_k: int, alpha: float
) -> list[SearchResult]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_hybrid_kb, kb_id, query, top_k, alpha)


async def _search_similarity_kb_async(
    kb_id: str, query: str, top_k: int, min_score: float
) -> list[SearchResult]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_similarity_kb, kb_id, query, top_k, min_score)


async def hybrid_search(
    query: str,
    kb_ids: list[str],
    top_k: int | None = None,
    alpha: float | None = None,
    mode: str = "hybrid",
    min_score: float = 0.0,
) -> list[SearchResult]:
    """Search across multiple KBs in parallel and merge with RRF.

    mode='hybrid': dense+sparse search, RRF score (alpha applies)
    mode='similarity': dense-only search, cosine score (alpha ignored, min_score applies)
    """
    cfg = get_settings().retrieval
    _top_k = top_k or cfg.top_k
    _alpha = alpha if alpha is not None else cfg.hybrid.alpha

    if mode == "similarity":
        if alpha is not None:
            logger.warning("alpha parameter is ignored in similarity mode")
        tasks = [
            _search_similarity_kb_async(kb_id, query, _top_k, min_score)
            for kb_id in kb_ids
        ]
    else:
        tasks = [
            _search_hybrid_kb_async(kb_id, query, _top_k, _alpha)
            for kb_id in kb_ids
        ]

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[list[SearchResult]] = []
    for kb_id, res in zip(kb_ids, raw_results):
        if isinstance(res, Exception):
            logger.error("KB search failed: kb=%s err=%s", kb_id, res)
            all_results.append([])
        else:
            all_results.append(res)  # type: ignore[arg-type]

    if mode == "similarity":
        merged = sorted(
            [r for results in all_results for r in results],
            key=lambda r: r.score,
            reverse=True,
        )
    else:
        from rag.merger import rrf_merge
        merged = rrf_merge(all_results)

    logger.info(
        "Search done: mode=%s kbs=%d candidates=%d",
        mode,
        len(kb_ids),
        len(merged),
    )
    return merged
