"""validate Op unit tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from exceptions import IngestValidationError


def _patch_redis(doc_etag=None):
    """Patch the redis ETag lookup used by validate()."""
    return patch("pipeline.ops.validate.redis_infra.get_doc_etag", return_value=doc_etag)


def test_validate_new_document():
    """New document (no ETag in Redis) → True."""
    with _patch_redis(doc_etag=None):
        from pipeline.ops.validate import validate

        assert validate("kb-test", "doc.pdf", "etag-abc") is True


def test_validate_same_etag_skips():
    """Unchanged ETag → False (skip)."""
    with _patch_redis(doc_etag="etag-abc"):
        from pipeline.ops.validate import validate

        assert validate("kb-test", "doc.pdf", "etag-abc") is False


def test_validate_different_etag_proceeds():
    """Changed ETag → True (re-process)."""
    with _patch_redis(doc_etag="etag-old"):
        from pipeline.ops.validate import validate

        assert validate("kb-test", "doc.pdf", "etag-new") is True


def test_validate_file_size_exceeded():
    """File too large → IngestValidationError."""
    with _patch_redis():
        from pipeline.ops.validate import validate

        with pytest.raises(IngestValidationError, match="File too large"):
            validate("kb-test", "doc.pdf", "etag-abc", file_size=300 * 1024 * 1024)


def test_validate_processing_does_not_skip():
    """Processing status no longer blocks validate — ETag check decides."""
    with _patch_redis(doc_etag=None):
        from pipeline.ops.validate import validate

        # status=processing is irrelevant now; no stored ETag → proceed
        assert validate("kb-test", "doc.pdf", "etag-abc") is True


def test_validate_force_skips_etag_check():
    """force=True bypasses ETag check → True regardless of stored ETag."""
    with _patch_redis(doc_etag="etag-abc"):
        from pipeline.ops.validate import validate

        assert validate("kb-test", "doc.pdf", "etag-abc", force=True) is True
