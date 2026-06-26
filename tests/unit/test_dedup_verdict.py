"""Unit tests for pipeline/ops/dedup/verdict.py."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import call, patch

from pipeline.ops.dedup.types import DedupResult
from pipeline.ops.dedup.verdict import handle_identical, handle_title_changed, run_verdict

_PG = "infra.postgres.update_doc_fields"
_GET_DOC = "infra.postgres.get_doc_by_id"
_UPDATE_PAYLOAD = "infra.qdrant.update_payload_by_doc_id"
_DEL_BANDS = "infra.postgres.delete_simhash_bands"

_TS_NEW = datetime(2026, 6, 26, 10, 0, 0, tzinfo=timezone.utc)
_TS_OLD = datetime(2026, 6, 25, 10, 0, 0, tzinfo=timezone.utc)


def _result(verdict, needs_indexing, duplicate_doc_id=None, title_hash="abc", content_simhash=12345):
    return DedupResult(
        verdict=verdict,
        needs_indexing=needs_indexing,
        duplicate_doc_id=duplicate_doc_id,
        title_hash=title_hash,
        content_simhash=content_simhash,
    )


def test_run_verdict_identical_dispatches():
    with patch("pipeline.ops.dedup.verdict.handle_identical") as mock_h, patch(_PG):
        run_verdict("doc-1", _result("identical", False, "doc-orig"), run_id="r1")
        mock_h.assert_called_once_with("doc-1", "doc-orig", "r1")


def test_run_verdict_title_changed_dispatches():
    with patch("pipeline.ops.dedup.verdict.handle_title_changed") as mock_h, patch(_PG):
        run_verdict("doc-2", _result("title_changed", False, "doc-old"), run_id="r2")
        mock_h.assert_called_once_with("doc-2", "doc-old", "r2")


def test_run_verdict_proceed_no_handler_called():
    with patch("pipeline.ops.dedup.verdict.handle_identical") as mock_i, \
         patch("pipeline.ops.dedup.verdict.handle_title_changed") as mock_t, \
         patch(_PG):
        run_verdict("doc-3", _result("proceed", True))
        mock_i.assert_not_called()
        mock_t.assert_not_called()


def test_run_verdict_saves_hashes_when_present():
    with patch(_PG) as mock_udf, patch("pipeline.ops.dedup.verdict.handle_identical"):
        run_verdict("doc-4", _result("identical", False, title_hash="h1", content_simhash=99))
        mock_udf.assert_any_call("doc-4", {"title_hash": "h1", "content_simhash": 99})


def test_run_verdict_skips_hash_save_when_empty():
    with patch(_PG) as mock_udf:
        run_verdict("doc-5", _result("proceed", True, title_hash=""))
        mock_udf.assert_not_called()


def test_run_verdict_unknown_verdict_logs_warning(caplog):
    with patch(_PG):
        with caplog.at_level(logging.WARNING, logger="pipeline.ops.dedup.verdict"):
            run_verdict("doc-6", _result("unknown", True))
    assert "unhandled verdict=unknown" in caplog.text


# ──────────────────────────────────────────────
# handle_title_changed
# ──────────────────────────────────────────────

def _make_doc(doc_id, kb_id="kb-1", source="s", source_uri="u", storage_key="k",
              title_hash="h", doc_created_at=None):
    return {
        "doc_id": doc_id, "kb_id": kb_id, "source": source,
        "source_uri": source_uri, "storage_key": storage_key,
        "title_hash": title_hash, "doc_created_at": doc_created_at,
    }


def test_title_changed_a_newer_updates_c():
    doc_a = _make_doc("doc-a", source="new.md", source_uri="uri-new", doc_created_at=_TS_NEW)
    doc_c = _make_doc("doc-c", source="old.md", source_uri="uri-old", doc_created_at=_TS_OLD)

    with patch(_GET_DOC, side_effect=[doc_a, doc_c]), \
         patch(_PG) as mock_udf, \
         patch(_UPDATE_PAYLOAD) as mock_qpay, \
         patch(_DEL_BANDS) as mock_del:
        handle_title_changed("doc-a", "doc-c", run_id="r1")

    mock_qpay.assert_called_once_with("kb-1", "doc-c", {"source": "new.md", "source_uri": "uri-new"})
    mock_udf.assert_any_call("doc-c", {"status": "outdated"})
    mock_del.assert_called_once_with("doc-c")
    mock_udf.assert_any_call("doc-a", {
        "status": "indexed", "run_id": "r1",
        "process_finished_at": mock_udf.call_args_list[-1][0][1]["process_finished_at"],
    })


def test_title_changed_c_newer_marks_a_outdated():
    doc_a = _make_doc("doc-a", doc_created_at=_TS_OLD)
    doc_c = _make_doc("doc-c", doc_created_at=_TS_NEW)

    with patch(_GET_DOC, side_effect=[doc_a, doc_c]), \
         patch(_PG) as mock_udf, \
         patch(_UPDATE_PAYLOAD) as mock_qpay, \
         patch(_DEL_BANDS) as mock_del:
        handle_title_changed("doc-a", "doc-c", run_id="r1")

    mock_qpay.assert_not_called()
    mock_del.assert_not_called()
    mock_udf.assert_called_once()
    assert mock_udf.call_args[0][1]["status"] == "outdated"


def test_title_changed_c_created_at_null_treats_a_as_newer():
    doc_a = _make_doc("doc-a", source="new.md", source_uri="u2", doc_created_at=_TS_NEW)
    doc_c = _make_doc("doc-c", doc_created_at=None)

    with patch(_GET_DOC, side_effect=[doc_a, doc_c]), \
         patch(_PG), \
         patch(_UPDATE_PAYLOAD) as mock_qpay, \
         patch(_DEL_BANDS):
        handle_title_changed("doc-a", "doc-c", run_id="r1")

    mock_qpay.assert_called_once()


def test_title_changed_no_duplicate_marks_outdated():
    with patch(_GET_DOC) as mock_get, patch(_PG) as mock_udf, patch(_UPDATE_PAYLOAD) as mock_qpay:
        handle_title_changed("doc-a", None, run_id="r1")

    mock_get.assert_not_called()
    mock_qpay.assert_not_called()
    assert mock_udf.call_args[0][1]["status"] == "outdated"
