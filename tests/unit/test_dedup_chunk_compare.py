"""Unit tests for pipeline/steps/dedup/chunk_compare.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from rag_api.pipeline.steps.chunk import ChunkResult
from rag_api.pipeline.steps.dedup.chunk_compare import (
    ChunkCompareScore,
    compare_chunks,
    run_chunk_compare,
    score_to_body_match,
)
from rag_api.pipeline.steps.dedup.types import DedupResult
from rag_api.pipeline.steps.embed import EmbeddedNode

_MODULE = "rag_api.pipeline.steps.dedup.chunk_compare"
_CHUNK = "rag_api.pipeline.steps.chunk.chunk"
_EMBED = "rag_api.pipeline.steps.embed.embed"
_SEARCH = "rag_api.infra.qdrant.search_chunks_by_doc_id"
_FINGERPRINTS = "rag_api.infra.postgres.get_docs_fingerprints"
_GET_DOC = "rag_api.infra.postgres.get_doc_by_id"


def _doc(file_name: str) -> MagicMock:
    doc = MagicMock()
    doc.metadata = {"file_name": file_name}
    return doc


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

    with patch(_CHUNK, return_value=ChunkResult(nodes=nodes)), \
         patch(_EMBED, return_value=embedded), \
         patch(_GET_DOC, return_value={"chunk_count": 2}), \
         patch(_SEARCH, side_effect=[[("p1", 0.9), ("p2", 0.3)], [("p3", 0.4)]]) as mock_search:
        score = compare_chunks(
            kb_id="kb-1", doc_id="doc-a", documents=[], candidate_doc_id="doc-c", cfg=_make_cfg()
        )

    # chunk 0 -> p1 (0.9 >= 0.5 threshold), chunk 1 -> no hit passes 0.5 threshold
    # chunk_ratio = min(2,2)/max(2,2) = 1.0, no scaling
    assert score.aggregate_score == 0.45
    assert len(score.matches) == 1
    assert score.matches[0].c_point_id == "p1"
    assert mock_search.call_count == 2


def test_compare_chunks_no_matches_zero_score():
    nodes = [MagicMock()]
    embedded = [_embedded_node()]

    with patch(_CHUNK, return_value=ChunkResult(nodes=nodes)), \
         patch(_EMBED, return_value=embedded), \
         patch(_GET_DOC, return_value={"chunk_count": 1}), \
         patch(_SEARCH, return_value=[("p1", 0.1)]):
        score = compare_chunks(
            kb_id="kb-1", doc_id="doc-a", documents=[], candidate_doc_id="doc-c", cfg=_make_cfg()
        )

    assert score.aggregate_score == 0.0
    assert score.matches == []


def test_compare_chunks_empty_documents_zero_score():
    with patch(_CHUNK, return_value=ChunkResult(nodes=[])), patch(_EMBED) as mock_embed:
        score = compare_chunks(
            kb_id="kb-1", doc_id="doc-a", documents=[], candidate_doc_id="doc-c", cfg=_make_cfg()
        )

    assert score.aggregate_score == 0.0
    mock_embed.assert_not_called()


def test_compare_chunks_scales_score_by_chunk_ratio():
    nodes = [MagicMock(), MagicMock(), MagicMock()]
    embedded = [_embedded_node(), _embedded_node(), _embedded_node()]

    with patch(_CHUNK, return_value=ChunkResult(nodes=nodes)), \
         patch(_EMBED, return_value=embedded), \
         patch(_GET_DOC, return_value={"chunk_count": 4}), \
         patch(_SEARCH, return_value=[("p1", 1.0)]):
        score = compare_chunks(
            kb_id="kb-1", doc_id="doc-a", documents=[], candidate_doc_id="doc-c", cfg=_make_cfg()
        )

    # raw coverage = 1.0 (all 3 A-chunks matched at score 1.0); chunk_ratio = 3/4 = 0.75
    assert score.aggregate_score == 0.75


def test_compare_chunks_skips_embed_when_chunk_ratio_below_similar_threshold():
    nodes = [MagicMock()]

    with patch(_CHUNK, return_value=ChunkResult(nodes=nodes)), \
         patch(_GET_DOC, return_value={"chunk_count": 10}), \
         patch(_EMBED) as mock_embed, \
         patch(_SEARCH) as mock_search:
        score = compare_chunks(
            kb_id="kb-1", doc_id="doc-a", documents=[], candidate_doc_id="doc-c", cfg=_make_cfg()
        )

    # chunk_ratio = 1/10 = 0.1 < body_similar_threshold(0.75) -> even a perfect raw score
    # couldn't clear the threshold once scaled, so embed+search are skipped entirely.
    assert score.aggregate_score == 0.0
    mock_embed.assert_not_called()
    mock_search.assert_not_called()


def test_compare_chunks_missing_candidate_chunk_count_skips():
    nodes = [MagicMock()]

    with patch(_CHUNK, return_value=ChunkResult(nodes=nodes)), \
         patch(_GET_DOC, return_value=None), \
         patch(_EMBED) as mock_embed:
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


def test_run_chunk_compare_confirms_identical_same_title():
    fingerprints = {"doc-c": {"title_hash": None}}
    with patch(f"{_MODULE}.compare_chunks", return_value=ChunkCompareScore("doc-c", 0.97)), \
         patch(_FINGERPRINTS, return_value=fingerprints):
        result = run_chunk_compare(
            doc_id="doc-a", kb_id="kb-1", documents=[_doc("a.md")], result=_similar_result(), cfg=_make_cfg()
        )

    assert result.body_match == "identical_level"
    assert result.needs_indexing is False
    assert result.duplicate_doc_id == "doc-c"
    assert result.candidate_doc_ids == ["doc-c"]
    assert result.title_match == "changed"


def test_run_chunk_compare_confirms_identical_title_matches_winner():
    from rag_api.pipeline.steps.dedup.simhash import compute_title_hash

    fingerprints = {"doc-c": {"title_hash": compute_title_hash("a.md")}}
    with patch(f"{_MODULE}.compare_chunks", return_value=ChunkCompareScore("doc-c", 0.97)), \
         patch(_FINGERPRINTS, return_value=fingerprints):
        result = run_chunk_compare(
            doc_id="doc-a", kb_id="kb-1", documents=[_doc("a.md")], result=_similar_result(), cfg=_make_cfg()
        )

    assert result.title_match == "same"


def test_run_chunk_compare_confirms_similar():
    with patch(f"{_MODULE}.compare_chunks", return_value=ChunkCompareScore("doc-c", 0.80)), \
         patch(_FINGERPRINTS, return_value={}):
        result = run_chunk_compare(
            doc_id="doc-a", kb_id="kb-1", documents=[_doc("a.md")], result=_similar_result(), cfg=_make_cfg()
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

    with patch(f"{_MODULE}.compare_chunks", side_effect=_side_effect) as mock_cc, \
         patch(_FINGERPRINTS, return_value={}):
        out = run_chunk_compare(doc_id="doc-a", kb_id="kb-1", documents=[_doc("a.md")], result=result, cfg=cfg)

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

    with patch(f"{_MODULE}.compare_chunks", side_effect=_side_effect), \
         patch(_FINGERPRINTS, return_value={}):
        out = run_chunk_compare(doc_id="doc-a", kb_id="kb-1", documents=[_doc("a.md")], result=result, cfg=cfg)

    assert out.duplicate_doc_id == "c1"
    assert out.candidate_doc_ids == ["c1"]
