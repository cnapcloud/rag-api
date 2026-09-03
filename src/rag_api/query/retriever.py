"""retriever.py — LlamaIndex VectorStoreIndex + Qdrant Hybrid / Similarity Search."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass

from rag_api.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class QueryResult:
    chunk_id: str
    kb_id: str
    doc_id: str
    doc_type: str
    title: str
    chunk_index: int | None
    page_num: int | None
    page_label: str | None
    text: str
    score: float
    rerank_score: float | None
    updated_at: str
    source_type: str = ""
    source: str = ""
    parent_chunk_id: str | None = None
    merged: bool = False


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


def _node_to_result(kb_id: str, node) -> QueryResult:
    meta = node.metadata
    source = meta.get("source", "")
    return QueryResult(
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
        parent_chunk_id=meta.get("parent_chunk_id"),
    )


def _filter_orphaned_chunks(results: list[QueryResult]) -> list[QueryResult]:
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


def _build_merged_result(a: dict, children: list[QueryResult]) -> QueryResult:
    """children -> one QueryResult representing ancestor `a` (a Postgres parent_chunks row dict,
    docs/internal/design/parent-child-chunking.md §5.1).

    Non-text/score fields are copied from children[0] — doc_id/kb_id/title/source_type/source/
    doc_type/updated_at are always identical across children of the same document. chunk_index
    is set to None: a merged block no longer maps to a single sequence position.
    """
    base = children[0]
    return QueryResult(
        chunk_id=a["chunk_id"], kb_id=base.kb_id, doc_id=base.doc_id, doc_type=base.doc_type,
        title=base.title, chunk_index=None, page_num=a["page_num"], page_label=a["page_label"],
        text=a["text"], score=sum(c.score for c in children) / len(children),
        rerank_score=None, updated_at=base.updated_at, source_type=base.source_type,
        source=base.source, parent_chunk_id=None, merged=True,
    )


def _auto_merge_parents(
    results: list[QueryResult], threshold: float, max_depth: int,
) -> list[QueryResult]:
    """Group leaf results by parent_chunk_id and replace groups meeting `threshold` with their
    ancestor's full text, repeating one level up (Postgres round-trip per level) until either no
    group merges or `max_depth` (non-leaf level count) is reached.

    docs/internal/design/parent-child-chunking.md §5.1. `settled` holds results that either have
    no parent_chunk_id (non-hierarchical documents) or already failed threshold at some level —
    keeping them out of `active` stops them from being retried at a higher level. Ancestors
    missing from get_parent_chunks() (pipeline interrupted mid-write) fall through to passthrough
    unchanged — same self-healing pattern as _filter_orphaned_chunks (§5.2). child_count is always
    >= 1 for any stored ancestor (chunk.py never stores child_count=0 rows), so the division
    below never raises ZeroDivisionError.
    """
    from rag_api.infra.postgres import get_parent_chunks

    active, settled = results, []
    for _ in range(max_depth):
        ids = {r.parent_chunk_id for r in active if r.parent_chunk_id}
        if not ids:
            break
        ancestors = get_parent_chunks(list(ids))

        groups: dict[str, list[QueryResult]] = defaultdict(list)
        passthrough: list[QueryResult] = []
        for r in active:
            if r.parent_chunk_id and r.parent_chunk_id in ancestors:
                groups[r.parent_chunk_id].append(r)
            else:
                passthrough.append(r)

        merged: list[QueryResult] = []
        any_merged = False
        for pid, children in groups.items():
            a = ancestors[pid]
            if len(children) / a["child_count"] >= threshold:
                r = _build_merged_result(a, children)
                r.parent_chunk_id = a["parent_id"]
                merged.append(r)
                any_merged = True
            else:
                merged.extend(children)

        settled.extend(passthrough)
        active = merged
        if not any_merged:
            break

    return settled + active


def _query_kb(
    kb_id: str,
    query: str,
    top_k: int,
    alpha: float,
    mode: str,
    min_score: float,
) -> list[QueryResult]:
    from rag_api.config.settings import resolve_settings

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
    results = [
        _node_to_result(kb_id, node)
        for node in nodes
        if mode != "similarity" or float(node.score or 0.0) >= min_score
    ]

    resolved = resolve_settings(kb_id)
    auto_merge = resolved.retrieval.auto_merge
    chunk_size = resolved.chunking.chunk_size
    max_depth = len(chunk_size) - 1 if isinstance(chunk_size, list) else 0
    if auto_merge.enabled and max_depth > 0:
        results = _auto_merge_parents(results, auto_merge.merge_threshold, max_depth)

    return results


async def query(
    query: str,
    kb_ids: list[str],
    top_k: int | None = None,
    alpha: float | None = None,
    mode: str = "hybrid",
    min_score: float = 0.0,
    rerank_enabled: bool | None = None,
    top_n: int | None = None,
) -> tuple[list[QueryResult], int, str, bool]:
    """Search across multiple KBs in parallel, merge, and optionally rerank.

    Returns: (results, total_candidates, rerank_provider, fallback_used)
    rerank_enabled: None uses settings value.
    mode='hybrid': dense+sparse search, RRF merge (alpha applies)
    mode='similarity': dense-only search, cosine score (alpha ignored, min_score applies)
    """
    from rag_api.query.reranker import rerank_async

    cfg = get_settings().retrieval
    _top_k = top_k or cfg.top_k
    _alpha = alpha if alpha is not None else cfg.hybrid.alpha
    _rerank_enabled = rerank_enabled if rerank_enabled is not None else cfg.rerank.enabled

    if mode == "similarity" and alpha is not None:
        logger.warning("alpha parameter is ignored in similarity mode")

    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(None, _query_kb, kb_id, query, _top_k, _alpha, mode, min_score)
        for kb_id in kb_ids
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[list[QueryResult]] = []
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
        from rag_api.query.merger import rrf_merge
        merged = rrf_merge(all_results, k=cfg.hybrid.rrf_k)[:_top_k]

    merged = _filter_orphaned_chunks(merged)

    total_candidates = len(merged)
    logger.info("Search done: mode=%s kbs=%d candidates=%d", mode, len(kb_ids), total_candidates)

    if _rerank_enabled and merged:
        _top_n = min(top_n or cfg.rerank.top_n, len(merged))
        results, provider, fallback = await rerank_async(query=query, results=merged, top_n=_top_n)
        return results, total_candidates, provider, fallback

    return merged, total_candidates, "none", False
