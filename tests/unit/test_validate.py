"""validate Op unit tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rag_api.exceptions import IngestValidationError

DOC_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def _no_kb_settings_overrides():
    """resolve_settings() always queries KB overrides — no-override case for these tests."""
    with patch("rag_api.infra.postgres.get_kb_settings_overrides", return_value={}):
        yield


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


def test_validate_applies_kb_scoped_max_file_size_override():
    """KB override for ingestion.max_file_size_mb actually changes validate() behavior
    end-to-end — proves the resolve_settings(doc["kb_id"]) wiring
    (docs/internal/design/kb-settings-override.md)."""
    from rag_api.exceptions import IngestValidationError
    from rag_api.pipeline.steps.validate import validate

    doc = _make_doc(50 * 1024 * 1024)  # 50 MB — within the 200 MB global default
    with (
        patch("rag_api.infra.postgres.get_doc_by_id", return_value=doc),
        patch(
            "rag_api.infra.postgres.get_kb_settings_overrides",
            return_value={"ingestion.max_file_size_mb": 10},
        ),
    ):
        with pytest.raises(IngestValidationError, match="File too large"):
            validate(DOC_ID)
