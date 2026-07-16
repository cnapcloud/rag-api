"""Unit tests for pipeline/step/dedup/__init__.py — non-document skip behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from llama_index.core import Document

from rag_api.pipeline.step.dedup import is_document, run_dedup_pipeline


def _doc(doc_type: str) -> Document:
    return Document(text="some body text", metadata={"doc_type": doc_type, "file_name": "f"})


# ──────────────────────────────────────────────
# is_document
# ──────────────────────────────────────────────

def test_is_document_true_for_document_type():
    assert is_document([_doc("pdf")]) is True


def test_is_document_false_for_code_type():
    assert is_document([_doc("py")]) is False


def test_is_document_false_for_config_type():
    assert is_document([_doc("yaml")]) is False


def test_is_document_true_when_no_documents():
    assert is_document([]) is True


# ──────────────────────────────────────────────
# run_dedup_pipeline — skips SimHash/MinHash for non-document types
# ──────────────────────────────────────────────

@patch("rag_api.pipeline.step.dedup.run_simhash_detection")
@patch("rag_api.config.settings.get_settings")
def test_run_dedup_pipeline_skips_non_document(mock_get_settings, mock_simhash):
    mock_get_settings.return_value = MagicMock(dedup=MagicMock(enabled=True))

    result = run_dedup_pipeline(doc_id="doc-1", kb_id="kb-1", documents=[_doc("py")])

    assert result.needs_indexing is True
    assert result.body_match == "none"
    mock_simhash.assert_not_called()


@patch("rag_api.pipeline.step.dedup.run_verdict")
@patch("rag_api.pipeline.step.dedup.run_simhash_detection")
@patch("rag_api.config.settings.get_settings")
def test_run_dedup_pipeline_runs_for_document(mock_get_settings, mock_simhash, mock_verdict):
    from rag_api.pipeline.step.dedup.types import DedupResult

    mock_get_settings.return_value = MagicMock(dedup=MagicMock(enabled=True))
    mock_simhash.return_value = DedupResult(body_match="identical_level", needs_indexing=False)

    result = run_dedup_pipeline(doc_id="doc-1", kb_id="kb-1", documents=[_doc("pdf")])

    mock_simhash.assert_called_once()
    assert result.body_match == "identical_level"


# ──────────────────────────────────────────────
# run_dedup_pipeline — routes 'similar' through chunk_compare (stage 3)
# ──────────────────────────────────────────────

@patch("rag_api.pipeline.step.dedup.run_verdict")
@patch("rag_api.pipeline.step.dedup.run_chunk_compare")
@patch("rag_api.pipeline.step.dedup.run_simhash_detection")
@patch("rag_api.config.settings.get_settings")
def test_run_dedup_pipeline_routes_similar_to_chunk_compare(
    mock_get_settings, mock_simhash, mock_chunk_compare, mock_verdict
):
    from rag_api.pipeline.step.dedup.types import DedupResult

    mock_get_settings.return_value = MagicMock(dedup=MagicMock(enabled=True))
    mock_simhash.return_value = DedupResult(
        body_match="similar", duplicate_doc_id="doc-c", needs_indexing=False
    )
    mock_chunk_compare.return_value = DedupResult(
        body_match="identical_level", duplicate_doc_id="doc-c", needs_indexing=False
    )

    result = run_dedup_pipeline(doc_id="doc-1", kb_id="kb-1", documents=[_doc("pdf")])

    mock_chunk_compare.assert_called_once()
    assert result.body_match == "identical_level"


@patch("rag_api.pipeline.step.dedup.run_verdict")
@patch("rag_api.pipeline.step.dedup.run_chunk_compare")
@patch("rag_api.pipeline.step.dedup.run_simhash_detection")
@patch("rag_api.config.settings.get_settings")
def test_run_dedup_pipeline_skips_chunk_compare_when_not_similar(
    mock_get_settings, mock_simhash, mock_chunk_compare, mock_verdict
):
    from rag_api.pipeline.step.dedup.types import DedupResult

    mock_get_settings.return_value = MagicMock(dedup=MagicMock(enabled=True))
    mock_simhash.return_value = DedupResult(body_match="identical_level", needs_indexing=False)

    run_dedup_pipeline(doc_id="doc-1", kb_id="kb-1", documents=[_doc("pdf")])

    mock_chunk_compare.assert_not_called()
