"""Unit tests for pipeline/utils/purge.purge_doc_artifacts."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from pipeline.utils.purge import purge_doc_artifacts

_DEL_CHUNKS = "infra.qdrant.delete_chunks_by_doc_id"
_DEL_SIMHASH = "infra.postgres.delete_simhash_bands"
_DEL_MINHASH = "infra.postgres.delete_minhash_bands"
_DEL_S3 = "infra.s3.delete_by_key"

DOC_ID = "doc-abc"
KB_ID = "kb-01"
STORAGE_KEY = "kb-01/file.pdf"


def test_all_three_called_with_chunks():
    with patch(_DEL_CHUNKS) as mock_chunks, \
            patch(_DEL_SIMHASH) as mock_sim, \
            patch(_DEL_MINHASH) as mock_min:
        purge_doc_artifacts(DOC_ID, KB_ID, include_chunks=True)

    mock_chunks.assert_called_once_with(KB_ID, DOC_ID)
    mock_sim.assert_called_once_with(DOC_ID)
    mock_min.assert_called_once_with(DOC_ID)


def test_include_chunks_false_skips_qdrant():
    with patch(_DEL_CHUNKS) as mock_chunks, \
            patch(_DEL_SIMHASH), patch(_DEL_MINHASH):
        purge_doc_artifacts(DOC_ID, KB_ID, include_chunks=False)

    mock_chunks.assert_not_called()


def test_empty_kb_id_skips_qdrant():
    with patch(_DEL_CHUNKS) as mock_chunks, \
            patch(_DEL_SIMHASH), patch(_DEL_MINHASH):
        purge_doc_artifacts(DOC_ID, kb_id="", include_chunks=True)

    mock_chunks.assert_not_called()


def test_storage_key_present_calls_s3():
    with patch(_DEL_CHUNKS), patch(_DEL_SIMHASH), patch(_DEL_MINHASH), \
            patch(_DEL_S3) as mock_s3:
        purge_doc_artifacts(DOC_ID, KB_ID, STORAGE_KEY, include_chunks=False)

    mock_s3.assert_called_once_with(STORAGE_KEY)


def test_no_storage_key_skips_s3():
    with patch(_DEL_CHUNKS), patch(_DEL_SIMHASH), patch(_DEL_MINHASH), \
            patch(_DEL_S3) as mock_s3:
        purge_doc_artifacts(DOC_ID, KB_ID, include_chunks=False)

    mock_s3.assert_not_called()


def test_swallow_false_propagates_exception():
    with patch(_DEL_CHUNKS, side_effect=RuntimeError("qdrant down")), \
            patch(_DEL_SIMHASH), patch(_DEL_MINHASH):
        with pytest.raises(RuntimeError, match="qdrant down"):
            purge_doc_artifacts(DOC_ID, KB_ID, include_chunks=True, swallow=False)


def test_swallow_true_continues_after_chunk_failure(caplog):
    with patch(_DEL_CHUNKS, side_effect=RuntimeError("qdrant down")), \
            patch(_DEL_SIMHASH) as mock_sim, \
            patch(_DEL_MINHASH) as mock_min, \
            caplog.at_level(logging.WARNING):
        purge_doc_artifacts(DOC_ID, KB_ID, include_chunks=True, swallow=True)

    assert "delete_chunks_by_doc_id" in caplog.text
    mock_sim.assert_called_once_with(DOC_ID)
    mock_min.assert_called_once_with(DOC_ID)


def test_swallow_true_continues_after_simhash_failure(caplog):
    with patch(_DEL_CHUNKS), \
            patch(_DEL_SIMHASH, side_effect=RuntimeError("pg down")), \
            patch(_DEL_MINHASH) as mock_min, \
            caplog.at_level(logging.WARNING):
        purge_doc_artifacts(DOC_ID, KB_ID, include_chunks=True, swallow=True)

    assert "delete_simhash_bands" in caplog.text
    mock_min.assert_called_once_with(DOC_ID)


def test_s3_client_error_always_swallowed(caplog):
    from botocore.exceptions import ClientError

    s3_error = ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "DeleteObject")

    with patch(_DEL_CHUNKS), patch(_DEL_SIMHASH), patch(_DEL_MINHASH), \
            patch(_DEL_S3, side_effect=s3_error), \
            caplog.at_level(logging.WARNING):
        purge_doc_artifacts(DOC_ID, KB_ID, STORAGE_KEY, swallow=False)

    assert "S3 deletion failed" in caplog.text
