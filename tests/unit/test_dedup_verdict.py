"""Unit tests for pipeline/ops/dedup/verdict.py."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import patch

from pipeline.ops.dedup.types import DedupResult
from pipeline.ops.dedup.verdict import handle_identical, handle_similar, handle_title_changed, run_verdict

_PG = "infra.postgres.update_doc_fields"
_GET_DOC = "infra.postgres.get_doc_by_id"
_UPDATE_PAYLOAD = "infra.qdrant.update_payload_by_doc_id"
_DEL_BANDS = "infra.postgres.delete_simhash_bands"
_DEL_MINHASH = "infra.postgres.delete_minhash_bands"
_DEL_CHUNKS = "infra.qdrant.delete_chunks_by_doc_id"

_TS_NEW = datetime(2026, 6, 26, 10, 0, 0, tzinfo=timezone.utc)
_TS_OLD = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)


def _result(body_match, title_match="unknown", needs_indexing=True, duplicate_doc_id=None,
            title_hash="abc", content_simhash=12345):
    return DedupResult(
        body_match=body_match,
        title_match=title_match,
        needs_indexing=needs_indexing,
        duplicate_doc_id=duplicate_doc_id,
        title_hash=title_hash,
        content_simhash=content_simhash,
    )


# ──────────────────────────────────────────────
# run_verdict dispatch
# ──────────────────────────────────────────────

def test_run_verdict_identical_dispatches():
    with patch("pipeline.ops.dedup.verdict.handle_identical") as mock_h, patch(_PG):
        run_verdict("doc-1", _result("identical_level", "same", False, "doc-orig"), run_id="r1")
        mock_h.assert_called_once_with("doc-1", "doc-orig")


def test_run_verdict_title_changed_dispatches():
    with patch("pipeline.ops.dedup.verdict.handle_title_changed") as mock_h, patch(_PG):
        run_verdict("doc-2", _result("identical_level", "changed", False, "doc-old"), run_id="r2")
        mock_h.assert_called_once_with("doc-2", "doc-old", "r2")


def test_run_verdict_proceed_no_handler_called():
    with patch("pipeline.ops.dedup.verdict.handle_identical") as mock_i, \
         patch("pipeline.ops.dedup.verdict.handle_title_changed") as mock_t:
        run_verdict("doc-3", _result("none"))
        mock_i.assert_not_called()
        mock_t.assert_not_called()


def test_run_verdict_similar_dispatches():
    result = _result("similar", needs_indexing=False, duplicate_doc_id="doc-c")

    with patch("pipeline.ops.dedup.verdict.handle_similar") as mock_h:
        run_verdict("doc-a", result, run_id="r1")
        mock_h.assert_called_once_with("doc-a", result, "r1")


def test_run_verdict_unknown_body_match_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="pipeline.ops.dedup.verdict"):
        run_verdict("doc-6", _result("unknown_body"))  # type: ignore[arg-type]
    assert "unhandled body_match=unknown_body" in caplog.text


# ──────────────────────────────────────────────
# handle_title_changed
# ──────────────────────────────────────────────

def _make_doc(doc_id, kb_id="kb-1", title="s", source="u", storage_key="k",
              title_hash="h", doc_created_at=None):
    return {
        "doc_id": doc_id, "kb_id": kb_id, "title": title,
        "source": source, "storage_key": storage_key,
        "title_hash": title_hash, "doc_created_at": doc_created_at,
    }


def test_title_changed_a_newer_updates_c():
    doc_a = _make_doc("doc-a", title="new.md", source="uri-new", doc_created_at=_TS_NEW)
    doc_c = _make_doc("doc-c", title="old.md", source="uri-old", doc_created_at=_TS_OLD)

    with patch(_GET_DOC, side_effect=[doc_a, doc_c]), \
         patch(_PG) as mock_udf, \
         patch(_UPDATE_PAYLOAD) as mock_qpay, \
         patch(_DEL_BANDS) as mock_del, \
         patch(_DEL_MINHASH):
        handle_title_changed("doc-a", "doc-c", run_id="r1")

    mock_qpay.assert_called_once_with("kb-1", "doc-c", {"title": "new.md", "source": "uri-new"})
    c_call = next(c for c in mock_udf.call_args_list if c[0][0] == "doc-c")
    assert c_call[0][1]["status"] == "outdated"
    assert c_call[0][1]["duplicate_of"] == "doc-a"
    assert c_call[0][1]["run_id"] == "r1"
    assert "process_finished_at" in c_call[0][1]
    mock_del.assert_called_once_with("doc-c")
    mock_udf.assert_any_call("doc-a", {
        "status": "indexed", "error": None, "run_id": "r1",
        "process_finished_at": mock_udf.call_args_list[-1][0][1]["process_finished_at"],
    })


def test_title_changed_c_newer_marks_a_outdated():
    doc_a = _make_doc("doc-a", doc_created_at=_TS_OLD)
    doc_c = _make_doc("doc-c", doc_created_at=_TS_NEW)

    with patch(_GET_DOC, side_effect=[doc_a, doc_c]), \
         patch(_PG) as mock_udf, \
         patch(_UPDATE_PAYLOAD) as mock_qpay, \
         patch(_DEL_BANDS) as mock_del, \
         patch(_DEL_MINHASH):
        handle_title_changed("doc-a", "doc-c", run_id="r1")

    mock_qpay.assert_not_called()
    mock_del.assert_not_called()
    mock_udf.assert_called_once()
    assert mock_udf.call_args[0][1]["status"] == "outdated"


def test_title_changed_c_created_at_null_treats_a_as_newer():
    doc_a = _make_doc("doc-a", title="new.md", source="u2", doc_created_at=_TS_NEW)
    doc_c = _make_doc("doc-c", doc_created_at=None)

    with patch(_GET_DOC, side_effect=[doc_a, doc_c]), \
         patch(_PG), \
         patch(_UPDATE_PAYLOAD) as mock_qpay, \
         patch(_DEL_BANDS), \
         patch(_DEL_MINHASH):
        handle_title_changed("doc-a", "doc-c", run_id="r1")

    mock_qpay.assert_called_once()


def test_title_changed_no_duplicate_marks_outdated():
    with patch(_GET_DOC) as mock_get, patch(_PG) as mock_udf, patch(_UPDATE_PAYLOAD) as mock_qpay:
        handle_title_changed("doc-a", None, run_id="r1")

    mock_get.assert_not_called()
    mock_qpay.assert_not_called()
    assert mock_udf.call_args[0][1]["status"] == "outdated"


# ──────────────────────────────────────────────
# handle_similar
# ──────────────────────────────────────────────

def test_similar_a_newer_deletes_c_chunks_and_marks_outdated():
    doc_a = _make_doc("doc-a", doc_created_at=_TS_NEW)
    doc_c = _make_doc("doc-c", kb_id="kb-1", doc_created_at=_TS_OLD)
    result = _result("similar", needs_indexing=False, duplicate_doc_id="doc-c")

    with patch(_GET_DOC, side_effect=[doc_a, doc_c]), \
         patch(_PG) as mock_udf, \
         patch(_DEL_CHUNKS) as mock_del_chunks, \
         patch(_DEL_BANDS), \
         patch(_DEL_MINHASH):
        handle_similar("doc-a", result, run_id="r1")

    assert result.needs_indexing is True
    mock_del_chunks.assert_called_once_with("kb-1", "doc-c")
    c_call = mock_udf.call_args_list[0]
    assert c_call[0][0] == "doc-c"
    assert c_call[0][1]["status"] == "outdated"
    assert c_call[0][1]["duplicate_of"] == "doc-a"
    assert c_call[0][1]["run_id"] == "r1"
    assert "process_finished_at" in c_call[0][1]
    # doc-a status is NOT set here — meta.py handles it after indexing
    assert all(c[0][0] != "doc-a" for c in mock_udf.call_args_list)


def test_similar_c_newer_marks_a_outdated_no_indexing():
    doc_a = _make_doc("doc-a", doc_created_at=_TS_OLD)
    doc_c = _make_doc("doc-c", doc_created_at=_TS_NEW)
    result = _result("similar", needs_indexing=False, duplicate_doc_id="doc-c")

    with patch(_GET_DOC, side_effect=[doc_a, doc_c]), patch(_PG) as mock_udf:
        handle_similar("doc-a", result, run_id="r1")

    assert result.needs_indexing is False
    assert mock_udf.call_args[0][1]["status"] == "outdated"


def test_similar_c_created_at_null_treats_a_as_newer():
    doc_a = _make_doc("doc-a", doc_created_at=_TS_NEW)
    doc_c = _make_doc("doc-c", doc_created_at=None)
    result = _result("similar", needs_indexing=False, duplicate_doc_id="doc-c")

    with patch(_GET_DOC, side_effect=[doc_a, doc_c]), patch(_PG), patch(_DEL_CHUNKS), patch(_DEL_BANDS), patch(_DEL_MINHASH):
        handle_similar("doc-a", result, run_id="r1")

    assert result.needs_indexing is True


def test_similar_no_duplicate_marks_outdated_no_indexing():
    result = _result("similar", needs_indexing=False, duplicate_doc_id=None)

    with patch(_GET_DOC) as mock_get, patch(_PG) as mock_udf:
        handle_similar("doc-a", result, run_id="r1")

    mock_get.assert_not_called()
    assert result.needs_indexing is False
    assert mock_udf.call_args[0][1]["status"] == "outdated"
