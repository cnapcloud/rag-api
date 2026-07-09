"""Unit tests for pipeline/ops/dedup/chunk_compare.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rag_api.pipeline.ops.dedup.chunk_compare import (
    ChunkCompareScore,
    compare_chunks,
    run_chunk_compare,
    score_to_body_match,
)
from rag_api.pipeline.ops.dedup.types import DedupResult
from rag_api.pipeline.ops.embed import EmbeddedNode

_MODULE = "rag_api.pipeline.ops.dedup.chunk_compare"
_CHUNK = "rag_api.pipeline.ops.chunk.chunk"
_EMBED = "rag_api.pipeline.ops.embed.embed"
_SEARCH = "rag_api.infra.qdrant.search_chunks_by_doc_id"


def _make_cfg(
    chunk_match_threshold: float = 0.50,
    body_identical_threshold: float = 0.95,
    body_similar_threshold: float = 0.75,
    compare_all_candidates: bool = False,
):
    cfg = MagicMock()
    cfg.chunk_match_threshold = chunk_match_threshold
    cfg.body_identical_threshold = body_identical_threshold
    cfg.body_similar_threshold = body_similar_threshold
    cfg.compare_all_candidates = compare_all_candidates
    return cfg


def _embedded_node(dense=(0.1, 0.2)) -> EmbeddedNode:
    node = MagicMock()
    return EmbeddedNode(node=node, dense_vector=list(dense), sparse_indices=[], sparse_values=[])


# ──────────────────────────────────────────────
# score_to_body_match
# ──────────────────────────────────────────────

def test_score_to_body_match_identical_at_threshold():
    assert score_to_body_match(0.95, _make_cfg()) == "identical_level"


def test_score_to_body_match_similar_just_below_identical():
    assert score_to_body_match(0.9499, _make_cfg()) == "similar"


def test_score_to_body_match_similar_at_threshold():
    assert score_to_body_match(0.75, _make_cfg()) == "similar"


def test_score_to_body_match_none_just_below_similar():
    assert score_to_body_match(0.7499, _make_cfg()) == "none"


def test_score_to_body_match_none_zero():
    assert score_to_body_match(0.0, _make_cfg()) == "none"


# ──────────────────────────────────────────────
# compare_chunks — coverage-weighted aggregate
# ──────────────────────────────────────────────

def test_compare_chunks_coverage_weighted_average():
    nodes = [MagicMock(), MagicMock()]
    embedded = [_embedded_node(), _embedded_node()]

    with patch(_CHUNK, return_value=nodes), \
         patch(_EMBED, return_value=embedded), \
         patch(_SEARCH, side_effect=[[("p1", 0.9), ("p2", 0.3)], [("p3", 0.4)]]) as mock_search:
        score = compare_chunks(
            kb_id="kb-1", doc_id="doc-a", documents=[], candidate_doc_id="doc-c", cfg=_make_cfg()
        )

    # chunk 0 -> p1 (0.9 >= 0.5 threshold), chunk 1 -> no hit passes 0.5 threshold
    assert score.aggregate_score == 0.45
    assert len(score.matches) == 1
    assert score.matches[0].c_point_id == "p1"
    assert mock_search.call_count == 2


def test_compare_chunks_no_matches_zero_score():
    nodes = [MagicMock()]
    embedded = [_embedded_node()]

    with patch(_CHUNK, return_value=nodes), \
         patch(_EMBED, return_value=embedded), \
         patch(_SEARCH, return_value=[("p1", 0.1)]):
        score = compare_chunks(
            kb_id="kb-1", doc_id="doc-a", documents=[], candidate_doc_id="doc-c", cfg=_make_cfg()
        )

    assert score.aggregate_score == 0.0
    assert score.matches == []


def test_compare_chunks_empty_documents_zero_score():
    with patch(_CHUNK, return_value=[]), patch(_EMBED) as mock_embed:
        score = compare_chunks(
            kb_id="kb-1", doc_id="doc-a", documents=[], candidate_doc_id="doc-c", cfg=_make_cfg()
        )

    assert score.aggregate_score == 0.0
    mock_embed.assert_not_called()


# ──────────────────────────────────────────────
# run_chunk_compare
# ──────────────────────────────────────────────

def _similar_result(duplicate_doc_id="doc-c", candidate_doc_ids=None):
    return DedupResult(
        body_match="similar",
        title_match="unknown",
        duplicate_doc_id=duplicate_doc_id,
        needs_indexing=False,
        title_hash="abc",
        content_simhash=123,
        candidate_doc_ids=candidate_doc_ids or ([duplicate_doc_id] if duplicate_doc_id else []),
    )


def test_run_chunk_compare_confirms_identical():
    with patch(f"{_MODULE}.compare_chunks", return_value=ChunkCompareScore("doc-c", 0.97)):
        result = run_chunk_compare(
            doc_id="doc-a", kb_id="kb-1", documents=[], result=_similar_result(), cfg=_make_cfg()
        )

    assert result.body_match == "identical_level"
    assert result.needs_indexing is False
    assert result.duplicate_doc_id == "doc-c"
    assert result.candidate_doc_ids == ["doc-c"]
    assert result.title_match == "unknown"


def test_run_chunk_compare_confirms_similar():
    with patch(f"{_MODULE}.compare_chunks", return_value=ChunkCompareScore("doc-c", 0.80)):
        result = run_chunk_compare(
            doc_id="doc-a", kb_id="kb-1", documents=[], result=_similar_result(), cfg=_make_cfg()
        )

    assert result.body_match == "similar"
    assert result.needs_indexing is False
    assert result.duplicate_doc_id == "doc-c"


def test_run_chunk_compare_downgrades_to_none_proceeds_to_indexing():
    with patch(f"{_MODULE}.compare_chunks", return_value=ChunkCompareScore("doc-c", 0.60)):
        result = run_chunk_compare(
            doc_id="doc-a", kb_id="kb-1", documents=[], result=_similar_result(), cfg=_make_cfg()
        )

    assert result.body_match == "none"
    assert result.needs_indexing is True
    assert result.duplicate_doc_id is None


def test_run_chunk_compare_no_candidates_returns_none():
    result = DedupResult(body_match="similar", duplicate_doc_id=None, candidate_doc_ids=[])

    with patch(f"{_MODULE}.compare_chunks") as mock_cc:
        out = run_chunk_compare(doc_id="doc-a", kb_id="kb-1", documents=[], result=result, cfg=_make_cfg())

    mock_cc.assert_not_called()
    assert out.body_match == "none"
    assert out.needs_indexing is True


def test_run_chunk_compare_all_candidates_picks_highest_score():
    cfg = _make_cfg(compare_all_candidates=True)
    result = _similar_result(duplicate_doc_id="c1", candidate_doc_ids=["c1", "c2"])

    def _side_effect(**kwargs):
        scores = {"c1": 0.80, "c2": 0.97}
        return ChunkCompareScore(kwargs["candidate_doc_id"], scores[kwargs["candidate_doc_id"]])

    with patch(f"{_MODULE}.compare_chunks", side_effect=_side_effect) as mock_cc:
        out = run_chunk_compare(doc_id="doc-a", kb_id="kb-1", documents=[], result=result, cfg=cfg)

    assert mock_cc.call_count == 2
    assert out.duplicate_doc_id == "c2"
    assert out.body_match == "identical_level"
    assert set(out.candidate_doc_ids) == {"c1", "c2"}


def test_run_chunk_compare_all_candidates_excludes_none_band_from_candidate_list():
    cfg = _make_cfg(compare_all_candidates=True)
    result = _similar_result(duplicate_doc_id="c1", candidate_doc_ids=["c1", "c2"])

    def _side_effect(**kwargs):
        scores = {"c1": 0.80, "c2": 0.10}
        return ChunkCompareScore(kwargs["candidate_doc_id"], scores[kwargs["candidate_doc_id"]])

    with patch(f"{_MODULE}.compare_chunks", side_effect=_side_effect):
        out = run_chunk_compare(doc_id="doc-a", kb_id="kb-1", documents=[], result=result, cfg=cfg)

    assert out.duplicate_doc_id == "c1"
    assert out.candidate_doc_ids == ["c1"]
