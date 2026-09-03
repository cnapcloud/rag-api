"""Unit tests for query/retriever.py's parent-child auto-merge —
docs/internal/design/parent-child-chunking.md §5."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rag_api.query.retriever import QueryResult, _auto_merge_parents

_GET_PARENTS = "rag_api.infra.postgres.get_parent_chunks"


def _result(chunk_id: str, score: float, parent_chunk_id: str | None = None) -> QueryResult:
    return QueryResult(
        chunk_id=chunk_id,
        kb_id="kb-1",
        doc_id="doc-a",
        doc_type="pdf",
        title="doc.pdf",
        chunk_index=0,
        page_num=None,
        page_label=None,
        text=f"text-{chunk_id}",
        score=score,
        rerank_score=None,
        updated_at="2026-01-01T00:00:00Z",
        parent_chunk_id=parent_chunk_id,
    )


def _ancestor(chunk_id: str, parent_id: str | None, child_count: int, text: str = "ancestor text") -> dict:
    return {
        "chunk_id": chunk_id, "doc_id": "doc-a", "kb_id": "kb-1", "level": 0,
        "parent_id": parent_id, "chunk_index": 0, "text": text, "child_count": child_count,
        "page_num": None, "page_label": None,
    }


# ──────────────────────────────────────────────
# 2-level — merge / no-merge threshold behavior
# ──────────────────────────────────────────────

def test_merges_when_ratio_meets_threshold():
    """2/3 matched >= 0.5 threshold -> replaced by the ancestor's full text."""
    results = [_result("c1", 0.9, "p1"), _result("c2", 0.8, "p1")]
    ancestors = {"p1": _ancestor("p1", parent_id=None, child_count=3, text="parent text")}

    with patch(_GET_PARENTS, return_value=ancestors) as mock_get:
        merged = _auto_merge_parents(results, threshold=0.5, max_depth=1)

    assert len(merged) == 1
    assert merged[0].chunk_id == "p1"
    assert merged[0].merged is True
    assert merged[0].text == "parent text"
    assert merged[0].score == pytest.approx(0.85)  # mean(0.9, 0.8)
    assert merged[0].chunk_index is None
    assert merged[0].parent_chunk_id is None  # ancestor's own parent_id (root, no further level)
    mock_get.assert_called_once_with(["p1"])


def test_does_not_merge_below_threshold():
    """1/3 matched < 0.5 threshold -> individual results returned unchanged."""
    results = [_result("c1", 0.9, "p1")]
    ancestors = {"p1": _ancestor("p1", parent_id=None, child_count=3)}

    with patch(_GET_PARENTS, return_value=ancestors):
        merged = _auto_merge_parents(results, threshold=0.5, max_depth=1)

    assert merged == results
    assert merged[0].merged is False


def test_results_without_parent_chunk_id_pass_through_unchanged():
    """Non-hierarchical documents (parent_chunk_id=None) are untouched."""
    results = [_result("c1", 0.9, None)]

    with patch(_GET_PARENTS) as mock_get:
        merged = _auto_merge_parents(results, threshold=0.5, max_depth=1)

    assert merged == results
    mock_get.assert_not_called()


def test_orphan_ancestor_missing_from_postgres_passes_through():
    """get_parent_chunks() missing an ID (interrupted pipeline) -> self-healing passthrough,
    same defensive pattern as _filter_orphaned_chunks (design §5.2)."""
    results = [_result("c1", 0.9, "ghost")]

    with patch(_GET_PARENTS, return_value={}):
        merged = _auto_merge_parents(results, threshold=0.5, max_depth=1)

    assert merged == results


def test_max_depth_zero_returns_unchanged():
    results = [_result("c1", 0.9, "p1")]

    with patch(_GET_PARENTS) as mock_get:
        merged = _auto_merge_parents(results, threshold=0.5, max_depth=0)

    assert merged == results
    mock_get.assert_not_called()


# ──────────────────────────────────────────────
# 3-level cascade — design §10 worked example
# ──────────────────────────────────────────────

def test_3level_cascade_matches_design_worked_example():
    """Reproduces docs/internal/design/parent-child-chunking.md §10.3-10.6 exactly:
    p0's 2/3 leaves merge into p0, but g0 (p0/p1/p2's parent) only sees 1/3 direct children
    promoted next round and fails its own threshold — so the cascade stops one level early,
    and c22 (which failed at its own level) is never retried against g0."""
    doc_x = _result("doc_X_chunk", 0.90, None)
    doc_y = _result("doc_Y_chunk", 0.80, None)
    c11 = _result("c11", 0.88, "a1b2c3d4:1")
    c13 = _result("c13", 0.85, "a1b2c3d4:1")
    c22 = _result("c22", 0.75, "a1b2c3d4:2")

    ancestors_round1 = {
        "a1b2c3d4:1": _ancestor("a1b2c3d4:1", parent_id="a1b2c3d4:0", child_count=3, text="p0 text"),
        "a1b2c3d4:2": _ancestor("a1b2c3d4:2", parent_id="a1b2c3d4:0", child_count=3, text="p1 text"),
    }
    ancestors_round2 = {
        "a1b2c3d4:0": _ancestor("a1b2c3d4:0", parent_id=None, child_count=3, text="g0 text"),
    }

    with patch(_GET_PARENTS, side_effect=[ancestors_round1, ancestors_round2]) as mock_get:
        merged = _auto_merge_parents(
            [doc_x, c11, c13, doc_y, c22], threshold=0.5, max_depth=2,
        )

    assert mock_get.call_count == 2  # one Postgres round-trip per level climbed

    by_id = {r.chunk_id: r for r in merged}
    assert set(by_id) == {"doc_X_chunk", "doc_Y_chunk", "c22", "a1b2c3d4:1"}

    merged_p0 = by_id["a1b2c3d4:1"]
    assert merged_p0.merged is True
    assert merged_p0.text == "p0 text"
    assert merged_p0.score == pytest.approx(0.865)  # mean(0.88, 0.85)
    assert merged_p0.parent_chunk_id == "a1b2c3d4:0"  # set after round 1, never retried/reset

    # c22 settled (below threshold) at round 1 and must not be retried at round 2
    assert by_id["c22"].merged is False
    assert by_id["c22"].text == "text-c22"


def test_settled_results_are_not_retried_at_higher_levels():
    """A result that fails threshold at level 1 must not reappear in the level-2 Postgres batch
    query — proves the settled/active split, independent of the full worked example above."""
    below_threshold = _result("c1", 0.9, "p1")
    ancestors_round1 = {"p1": _ancestor("p1", parent_id="g0", child_count=10)}  # 1/10 < 0.5

    with patch(_GET_PARENTS, return_value=ancestors_round1) as mock_get:
        merged = _auto_merge_parents([below_threshold], threshold=0.5, max_depth=3)

    # any_merged=False after round 1 -> loop breaks, get_parent_chunks called exactly once
    mock_get.assert_called_once_with(["p1"])
    assert merged == [below_threshold]
