"""Unit tests for the BeforeDocCreate hook on the upload routes (US-51)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from rag_api.api.app import create_app
from rag_api.hooks import BeforeDocCreate, HookAbort, register

KB_ID = "kb-01"


@pytest.fixture
def client():
    with patch("rag_api.api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def kb(mock_postgres):
    mock_postgres.register_kb(KB_ID, "KB 01")
    return mock_postgres


@pytest.fixture
def _s3_and_queue():
    with (
        patch("rag_api.infra.s3.upload_object", return_value="etag-123"),
        patch("rag_api.pipeline.queue.enqueue.enqueue_upload_event") as enq,
    ):
        yield enq


class TestUploadDocHook:
    def test_emits_before_doc_create_for_new_doc(self, client, kb, _s3_and_queue, reset_hooks):
        events: list[BeforeDocCreate] = []
        register(BeforeDocCreate, events.append)

        resp = client.post(
            f"/api/kb/{KB_ID}/docs/upload",
            files={"file": ("report.txt", b"hello world", "text/plain")},
        )

        assert resp.status_code == 202
        assert len(events) == 1
        assert events[0].kb_id == KB_ID
        assert events[0].source_type == "s3"
        assert events[0].principal is None  # no OIDC middleware in the bare app

    def test_hookabort_maps_to_403_and_skips_create(self, client, kb, _s3_and_queue, reset_hooks):
        def deny(ev: BeforeDocCreate) -> None:
            raise HookAbort("KB document limit reached")

        register(BeforeDocCreate, deny)

        with patch("rag_api.infra.postgres.create_doc") as create_doc:
            resp = client.post(
                f"/api/kb/{KB_ID}/docs/upload",
                files={"file": ("report.txt", b"hello world", "text/plain")},
            )

        assert resp.status_code == 403
        assert "limit reached" in resp.json()["detail"]
        create_doc.assert_not_called()
        _s3_and_queue.assert_not_called()

    def test_no_hook_registered_is_a_regression_noop(self, client, kb, _s3_and_queue, reset_hooks):
        resp = client.post(
            f"/api/kb/{KB_ID}/docs/upload",
            files={"file": ("report.txt", b"hello world", "text/plain")},
        )

        assert resp.status_code == 202
        _s3_and_queue.assert_called_once()


class TestUploadBatchHook:
    def test_hookabort_marks_current_and_remaining_as_error(
        self, client, kb, _s3_and_queue, reset_hooks
    ):
        seen: list[str] = []

        def deny_after_first(ev: BeforeDocCreate) -> None:
            seen.append(ev.kb_id)
            if len(seen) >= 2:
                raise HookAbort("KB document limit reached")

        register(BeforeDocCreate, deny_after_first)

        resp = client.post(
            f"/api/kb/{KB_ID}/docs/upload/batch",
            files=[
                ("files", ("a.txt", b"aaa", "text/plain")),
                ("files", ("b.txt", b"bbb", "text/plain")),
                ("files", ("c.txt", b"ccc", "text/plain")),
            ],
        )

        assert resp.status_code == 202
        results = resp.json()["results"]
        assert len(results) == 3
        assert "error" not in results[0]
        assert results[1]["status"] == "error" and "limit reached" in results[1]["error"]
        assert results[2]["status"] == "error" and "limit reached" in results[2]["error"]
        # third file never reached the hook
        assert seen == [KB_ID, KB_ID]
