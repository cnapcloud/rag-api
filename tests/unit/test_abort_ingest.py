"""Unit tests for pipeline/utils/abort_ingest.abort_active_ingest."""

from __future__ import annotations

import logging
from unittest.mock import patch

from rag_api.pipeline.utils.abort_ingest import abort_active_ingest

_DEQUEUE = "rag_api.pipeline.queue.enqueue.dequeue_upload_events"
_SET_FAILED = "rag_api.pipeline.utils.doc_state.set_failed"
_FIND_RUN_IDS = "rag_api.infra.dagster_utils.find_active_run_ids_by_doc_ids"
_TERMINATE = "rag_api.infra.dagster_utils.terminate_dagster_run"


def test_empty_docs_is_noop():
    with patch(_DEQUEUE) as mock_dequeue, patch(_SET_FAILED) as mock_failed, \
            patch(_TERMINATE) as mock_terminate:
        result = abort_active_ingest([])

    assert result == (0, 0)
    mock_dequeue.assert_not_called()
    mock_failed.assert_not_called()
    mock_terminate.assert_not_called()


def test_pending_doc_dequeued_and_failed_no_run_lookup():
    doc = {"doc_id": "doc-pending", "status": "pending", "run_id": ""}

    with patch(_DEQUEUE) as mock_dequeue, patch(_SET_FAILED) as mock_failed, \
            patch(_FIND_RUN_IDS) as mock_lookup, patch(_TERMINATE) as mock_terminate:
        result = abort_active_ingest([doc])

    assert result == (1, 0)
    mock_dequeue.assert_called_once_with("doc-pending")
    mock_failed.assert_called_once_with("doc-pending", "Aborted")
    mock_lookup.assert_not_called()
    mock_terminate.assert_not_called()


def test_running_doc_with_run_id_dequeued_and_terminated_directly():
    doc = {"doc_id": "doc-running", "status": "running", "run_id": "run-abc"}

    with patch(_DEQUEUE) as mock_dequeue, patch(_SET_FAILED) as mock_failed, \
            patch(_FIND_RUN_IDS) as mock_lookup, patch(_TERMINATE) as mock_terminate:
        result = abort_active_ingest([doc])

    assert result == (1, 1)
    mock_dequeue.assert_called_once_with("doc-running")
    mock_failed.assert_called_once_with("doc-running", "Aborted")
    mock_lookup.assert_not_called()
    mock_terminate.assert_called_once_with("run-abc")


def test_running_doc_without_run_id_looked_up_by_doc_id_tag():
    doc = {"doc_id": "doc-queued", "status": "running", "run_id": ""}

    with patch(_DEQUEUE) as mock_dequeue, patch(_SET_FAILED), \
            patch(_FIND_RUN_IDS, return_value=["run-queued"]) as mock_lookup, \
            patch(_TERMINATE) as mock_terminate:
        result = abort_active_ingest([doc])

    assert result == (1, 1)
    mock_dequeue.assert_called_once_with("doc-queued")
    mock_lookup.assert_called_once_with(["doc-queued"])
    mock_terminate.assert_called_once_with("run-queued")


def test_mixed_pending_and_running_docs_all_dequeued():
    pending = {"doc_id": "doc-a", "status": "pending", "run_id": ""}
    running = {"doc_id": "doc-b", "status": "running", "run_id": "run-b"}

    with patch(_DEQUEUE) as mock_dequeue, patch(_SET_FAILED) as mock_failed, \
            patch(_FIND_RUN_IDS), patch(_TERMINATE) as mock_terminate:
        result = abort_active_ingest([pending, running])

    assert result == (2, 1)
    assert mock_dequeue.call_count == 2
    mock_dequeue.assert_any_call("doc-a")
    mock_dequeue.assert_any_call("doc-b")
    assert mock_failed.call_count == 2
    mock_terminate.assert_called_once_with("run-b")


def test_terminate_failure_is_swallowed(caplog):
    doc = {"doc_id": "doc-running", "status": "running", "run_id": "run-abc"}

    with patch(_DEQUEUE), patch(_SET_FAILED), patch(_FIND_RUN_IDS), \
            patch(_TERMINATE, side_effect=RuntimeError("dagster down")), \
            caplog.at_level(logging.WARNING):
        result = abort_active_ingest([doc])

    assert result == (1, 1)
    assert "Dagster terminate failed" in caplog.text
