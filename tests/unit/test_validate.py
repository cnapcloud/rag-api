"""validate Op unit tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rag_api.exceptions import IngestValidationError

DOC_ID = "11111111-1111-1111-1111-111111111111"


def _make_doc(file_size: int = 1024) -> dict:
    return {"doc_id": DOC_ID, "kb_id": "kb-test", "file_size": file_size, "status": "pending"}


def test_validate_normal_doc():
    """Normal doc within size limit -> True."""
    with patch("rag_api.infra.postgres.get_doc_by_id", return_value=_make_doc()):
        from rag_api.pipeline.steps.validate import validate
        assert validate(DOC_ID) is True


def test_validate_doc_not_found():
    """Non-existent doc_id -> IngestValidationError."""
    with patch("rag_api.infra.postgres.get_doc_by_id", return_value=None):
        from rag_api.pipeline.steps.validate import validate
        with pytest.raises(IngestValidationError, match="Document not found"):
            validate(DOC_ID)


def test_validate_file_size_exceeded():
    """File too large -> IngestValidationError."""
    with patch("rag_api.infra.postgres.get_doc_by_id", return_value=_make_doc(300 * 1024 * 1024)):
        from rag_api.pipeline.steps.validate import validate
        with pytest.raises(IngestValidationError, match="File too large"):
            validate(DOC_ID)


def test_validate_zero_size_passes():
    """file_size=0 -> no size check, returns True."""
    with patch("rag_api.infra.postgres.get_doc_by_id", return_value=_make_doc(0)):
        from rag_api.pipeline.steps.validate import validate
        assert validate(DOC_ID) is True


def test_validate_none_size_passes():
    """file_size=None -> no size check, returns True."""
    doc = _make_doc()
    doc["file_size"] = None
    with patch("rag_api.infra.postgres.get_doc_by_id", return_value=doc):
        from rag_api.pipeline.steps.validate import validate
        assert validate(DOC_ID) is True


def test_validate_force_flag_passes():
    """force=True -> validate still passes (force does not change size check)."""
    with patch("rag_api.infra.postgres.get_doc_by_id", return_value=_make_doc()):
        from rag_api.pipeline.steps.validate import validate
        assert validate(DOC_ID, force=True) is True
