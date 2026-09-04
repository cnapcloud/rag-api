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
    def test_hookabort_records_blocked_plus_skipped_and_returns_403(
        self, client, kb, _s3_and_queue, reset_hooks
    ):
        seen: list[str] = []

        def deny_after_first(ev: BeforeDocCreate) -> None:
            seen.append(ev.kb_id)
            if len(seen) >= 2:
                raise HookAbort("KB document limit reached: 3/3 (authz.max_docs_count)")

        register(BeforeDocCreate, deny_after_first)

        resp = client.post(
            f"/api/kb/{KB_ID}/docs/upload/batch",
            files=[
                ("files", ("a.txt", b"aaa", "text/plain")),
                ("files", ("b.txt", b"bbb", "text/plain")),
                ("files", ("c.txt", b"ccc", "text/plain")),
            ],
        )

        assert resp.status_code == 403
        body = resp.json()
        assert body["detail"] == "KB document limit reached: 3/3 (authz.max_docs_count)"
        # results stay 1:1 with the submitted files: a ok, b blocked, c skipped.
        results = body["results"]
        assert len(results) == 3
        assert "error" not in results[0]
        assert results[1]["title"] == "b.txt"
        assert results[1]["error"] == "KB document limit reached: 3/3 (authz.max_docs_count)"
        assert results[2]["title"] == "c.txt" and "Skipped" in results[2]["error"]
        # c.txt never reached the hook
        assert seen == [KB_ID, KB_ID]

    def test_first_file_blocked_returns_403_with_all_items(
        self, client, kb, _s3_and_queue, reset_hooks
    ):
        def deny(ev: BeforeDocCreate) -> None:
            raise HookAbort("KB document limit reached: 3/3")

        register(BeforeDocCreate, deny)

        resp = client.post(
            f"/api/kb/{KB_ID}/docs/upload/batch",
            files=[
                ("files", ("a.txt", b"aaa", "text/plain")),
                ("files", ("b.txt", b"bbb", "text/plain")),
            ],
        )

        assert resp.status_code == 403
        body = resp.json()
        assert "limit reached" in body["detail"]
        assert len(body["results"]) == 2
        assert all(r["status"] == "error" for r in body["results"])
        _s3_and_queue.assert_not_called()

    def test_unsupported_extension_is_recorded_and_batch_continues_422(
        self, client, kb, _s3_and_queue, reset_hooks
    ):
        resp = client.post(
            f"/api/kb/{KB_ID}/docs/upload/batch",
            files=[
                ("files", ("notes.md", b"# notes", "text/markdown")),
                ("files", ("archive.zip", b"PK\x03\x04", "application/zip")),
                ("files", ("summary.md", b"# summary", "text/markdown")),
            ],
        )

        # Unsupported extension fails that item; the batch still processes the rest.
        assert resp.status_code == 422
        body = resp.json()
        assert "Unsupported file format" in body["detail"]
        results = body["results"]
        assert len(results) == 3
        assert "error" not in results[0]
        assert results[1]["title"] == "archive.zip" and results[1]["status"] == "error"
        assert "error" not in results[2]

    def test_all_files_succeed_returns_202_with_results(
        self, client, kb, _s3_and_queue, reset_hooks
    ):
        resp = client.post(
            f"/api/kb/{KB_ID}/docs/upload/batch",
            files=[
                ("files", ("a.txt", b"aaa", "text/plain")),
                ("files", ("b.txt", b"bbb", "text/plain")),
            ],
        )

        assert resp.status_code == 202
        body = resp.json()
        assert "detail" not in body
        assert len(body["results"]) == 2
        assert all("doc_id" in r for r in body["results"])
