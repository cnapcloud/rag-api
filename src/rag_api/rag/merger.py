"""merger.py — 복수 KB 검색 결과 RRF(Reciprocal Rank Fusion) 머지."""

from __future__ import annotations

from rag_api.rag.retriever import SearchResult


def rrf_merge(
    result_lists: list[list[SearchResult]],
    k: int = 60,
) -> list[SearchResult]:
    """
    Reciprocal Rank Fusion으로 복수 KB 결과를 머지한다.

    score_rrf = Σ 1 / (k + rank_i)
    """
    scores: dict[str, float] = {}
    chunk_map: dict[str, SearchResult] = {}

    for results in result_lists:
        for rank, result in enumerate(results, start=1):
            cid = result.chunk_id
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            chunk_map[cid] = result

    # RRF 점수로 정렬 후 score 필드에 반영
    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    merged: list[SearchResult] = []
    for cid in sorted_ids:
        result = chunk_map[cid]
        result.score = round(scores[cid], 6)
        merged.append(result)

    return merged