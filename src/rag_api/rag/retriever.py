"""retriever.py — LlamaIndex VectorStoreIndex + Qdrant Hybrid / Similarity Search."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from rag_api.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    chunk_id: str
    kb_id: str
    doc_id: str
    doc_type: str
    title: str
    chunk_index: int
    page_num: int | None
    page_label: str | None
    text: str
    score: float
    rerank_score: float | None
    updated_at: str
    source_type: str = ""
    source: str = ""


def _build_vector_store(kb_id: str, qdrant_client=None):
    from llama_index.vector_stores.qdrant import QdrantVectorStore

    from rag_api.infra.qdrant import get_qdrant_client
    from rag_api.pipeline.utils.sparse import compute_sparse_tf

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

    from rag_api.pipeline.steps.embed import build_embed_model

    vector_store = _build_vector_store(kb_id)
    em = embed_model or build_embed_model()
    return VectorStoreIndex.from_vector_store(vector_store, embed_model=em)


def _node_to_result(kb_id: str, node) -> SearchResult:
    meta = node.metadata
    source = meta.get("source", "")
    return SearchResult(
        chunk_id=node.node_id,
        kb_id=kb_id,
        doc_id=meta.get("doc_id", ""),
        title=meta.get("title", ""),
        source_type=meta.get("source_type", ""),
        source=source,
        doc_type=meta.get("doc_type", ""),
        chunk_index=int(meta.get("chunk_index", 0)),
        page_num=meta.get("page_num"),
        page_label=str(v) if (v := meta.get("page_label")) is not None else None,
        text=node.get_content(),
        score=float(node.score or 0.0),
        rerank_score=None,
        updated_at=meta.get("updated_at", ""),
    )


def _filter_orphaned_chunks(results: list[SearchResult]) -> list[SearchResult]:
    """Drop chunks whose doc_id no longer has a Postgres row, purging them from Qdrant.

    Qdrant chunk deletion is best-effort on non-indexed statuses
    (pipeline/steps/delete.py: _delete_qdrant_chunks), so a document row removed
    while its chunks are being written/deleted can leave orphaned chunks behind.
    Purging on detection is self-healing — best-effort, never blocks the search response.
    """
    from rag_api.infra import qdrant as qdrant_infra
    from rag_api.infra.postgres import get_existing_doc_ids

    doc_ids = {r.doc_id for r in results if r.doc_id}
    existing = get_existing_doc_ids(list(doc_ids))

    kept = []
    purged: set[tuple[str, str]] = set()
    for r in results:
        if r.doc_id and r.doc_id in existing:
            kept.append(r)
            continue

        logger.warning(
            "Orphaned chunk excluded from search results: kb=%s doc_id=%s chunk_id=%s",
            r.kb_id, r.doc_id, r.chunk_id,
        )
        key = (r.kb_id, r.doc_id)
        if key in purged:
            continue
        purged.add(key)
        try:
            qdrant_infra.delete_chunks_by_doc_id(r.kb_id, r.doc_id)
        except Exception as e:
            logger.warning(
                "Failed to purge orphaned chunk from Qdrant (ignored): kb=%s doc_id=%s err=%s",
                r.kb_id, r.doc_id, e,
            )
    return kept


def _search_kb(
    kb_id: str,
    query: str,
    top_k: int,
    alpha: float,
    mode: str,
    min_score: float,
) -> list[SearchResult]:
    index = _build_index(kb_id)
    if mode == "similarity":
        retriever = index.as_retriever(
            similarity_top_k=top_k,
            vector_store_query_mode="default",
        )
    else:
        retriever = index.as_retriever(
            similarity_top_k=top_k,
            vector_store_query_mode="hybrid",
            alpha=alpha,
        )

    nodes = retriever.retrieve(query)
    return [
        _node_to_result(kb_id, node)
        for node in nodes
        if mode != "similarity" or float(node.score or 0.0) >= min_score
    ]


async def search(
    query: str,
    kb_ids: list[str],
    top_k: int | None = None,
    alpha: float | None = None,
    mode: str = "hybrid",
    min_score: float = 0.0,
    rerank_enabled: bool | None = None,
    top_n: int | None = None,
) -> tuple[list[SearchResult], int, str, bool]:
    """Search across multiple KBs in parallel, merge, and optionally rerank.

    Returns: (results, total_candidates, rerank_provider, fallback_used)
    rerank_enabled: None uses settings value.
    mode='hybrid': dense+sparse search, RRF merge (alpha applies)
    mode='similarity': dense-only search, cosine score (alpha ignored, min_score applies)
    """
    from rag_api.rag.reranker import rerank_async

    cfg = get_settings().retrieval
    _top_k = top_k or cfg.top_k
    _alpha = alpha if alpha is not None else cfg.hybrid.alpha
    _rerank_enabled = rerank_enabled if rerank_enabled is not None else cfg.rerank.enabled

    if mode == "similarity" and alpha is not None:
        logger.warning("alpha parameter is ignored in similarity mode")

    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(None, _search_kb, kb_id, query, _top_k, _alpha, mode, min_score)
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
        )[:_top_k]
    else:
        from rag_api.rag.merger import rrf_merge
        merged = rrf_merge(all_results, k=cfg.hybrid.rrf_k)[:_top_k]

    merged = _filter_orphaned_chunks(merged)

    total_candidates = len(merged)
    logger.info("Search done: mode=%s kbs=%d candidates=%d", mode, len(kb_ids), total_candidates)

    if _rerank_enabled and merged:
        _top_n = min(top_n or cfg.rerank.top_n, len(merged))
        results, provider, fallback = await rerank_async(query=query, results=merged, top_n=_top_n)
        return results, total_candidates, provider, fallback

    return merged, total_candidates, "none", False
