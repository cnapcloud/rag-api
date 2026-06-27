"""Unit tests for GET /api/kb/{kb_id}/docs — pagination, search, sort."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.fixture
def client():
    with patch("api.app._init_infrastructure"):
        app = create_app()
    return TestClient(app)


def _make_doc(source: str, status: str = "indexed", chunk_count: int | None = None) -> dict:
    return {
        "doc_id": "11111111-0000-0000-0000-000000000001",
        "kb_id": "kb1",
        "title": source,
        "source": source,
        "source_type": "s3",
        "status": status,
        "doc_type": "pdf",
        "chunk_count": chunk_count,
        "file_size": 1024,
        "embedding_model": "ollama/nomic-embed-text",
        "error": None,
        "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-01T00:01:00+00:00",
    }


class TestListDocsDefaultResponse:
    def test_returns_paginated_shape(self, client):
        items = [_make_doc(f"doc{i}.pdf") for i in range(3)]
        with patch("infra.postgres.list_docs_paginated", return_value=(items, 3)):
            resp = client.get("/api/kb/kb1/docs")

        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert "page" in body
        assert "page_size" in body
        assert body["total"] == 3
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert len(body["items"]) == 3

    def test_default_params_passed_to_postgres(self, client):
        captured = {}

        def fake_paginated(kb_id, page, page_size, status, search, sort_by, sort_order, source_type=None):
            captured.update(locals())
            return ([], 0)

        with patch("infra.postgres.list_docs_paginated", side_effect=fake_paginated):
            client.get("/api/kb/kb1/docs")

        assert captured["page"] == 1
        assert captured["page_size"] == 20
        assert captured["status"] is None
        assert captured["search"] is None
        assert captured["sort_by"] == "updated_at"
        assert captured["sort_order"] == "desc"


class TestListDocsPagination:
    def test_page2_passed_correctly(self, client):
        captured = {}

        def fake_paginated(kb_id, page, page_size, status, search, sort_by, sort_order, source_type=None):
            captured["page"] = page
            captured["page_size"] = page_size
            return ([], 50)

        with patch("infra.postgres.list_docs_paginated", side_effect=fake_paginated):
            resp = client.get("/api/kb/kb1/docs?page=2&page_size=10")

        assert resp.status_code == 200
        assert captured["page"] == 2
        assert captured["page_size"] == 10
        body = resp.json()
        assert body["page"] == 2
        assert body["page_size"] == 10

    def test_out_of_range_page_returns_empty_items(self, client):
        with patch("infra.postgres.list_docs_paginated", return_value=([], 5)):
            resp = client.get("/api/kb/kb1/docs?page=999")

        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 5

    def test_page_size_clamped_to_100(self, client):
        captured = {}

        def fake_paginated(kb_id, page, page_size, status, search, sort_by, sort_order, source_type=None):
            captured["page_size"] = page_size
            return ([], 0)

        with patch("infra.postgres.list_docs_paginated", side_effect=fake_paginated):
            resp = client.get("/api/kb/kb1/docs?page_size=999")

        assert resp.status_code == 200
        assert captured["page_size"] == 100
        assert resp.json()["page_size"] == 100

    def test_page_less_than_1_returns_422(self, client):
        with patch("infra.postgres.list_docs_paginated", return_value=([], 0)):
            resp = client.get("/api/kb/kb1/docs?page=0")
        assert resp.status_code == 422


class TestListDocsSearch:
    def test_search_param_forwarded(self, client):
        captured = {}

        def fake_paginated(kb_id, page, page_size, status, search, sort_by, sort_order, source_type=None):
            captured["search"] = search
            return ([], 0)

        with patch("infra.postgres.list_docs_paginated", side_effect=fake_paginated):
            client.get("/api/kb/kb1/docs?search=report")

        assert captured["search"] == "report"

    def test_search_case_insensitive_in_store(self):
        """FakePostgresStore filters case-insensitively on source."""
        from tests.conftest import FakePostgresStore

        store = FakePostgresStore()
        store.register_kb("kb1")
        store.create_doc("kb1", "Reports/Q1.pdf", "Reports/Q1.pdf", "s3", status="indexed")
        store.create_doc("kb1", "archive/old.pdf", "archive/old.pdf", "s3", status="indexed")

        items, total = store.list_docs_paginated("kb1", 1, 20, search="report")
        assert total == 1
        assert items[0]["title"] == "Reports/Q1.pdf"


class TestListDocsStatusFilter:
    def test_status_param_forwarded(self, client):
        captured = {}

        def fake_paginated(kb_id, page, page_size, status, search, sort_by, sort_order, source_type=None):
            captured["status"] = status
            return ([], 0)

        with patch("infra.postgres.list_docs_paginated", side_effect=fake_paginated):
            client.get("/api/kb/kb1/docs?status=indexed")

        assert captured["status"] == "indexed"

    def test_status_filter_in_store(self):
        from tests.conftest import FakePostgresStore

        store = FakePostgresStore()
        store.register_kb("kb1")
        store.create_doc("kb1", "a.pdf", "a.pdf", "s3", status="indexed")
        store.create_doc("kb1", "b.pdf", "b.pdf", "s3", status="failed")
        store.create_doc("kb1", "c.pdf", "c.pdf", "s3", status="indexed")

        items, total = store.list_docs_paginated("kb1", 1, 20, status="indexed")
        assert total == 2
        assert all(d["status"] == "indexed" for d in items)


class TestListDocsSort:
    def test_sort_by_title_param_forwarded(self, client):
        captured = {}

        def fake_paginated(kb_id, page, page_size, status, search, sort_by, sort_order, source_type=None):
            captured["sort_by"] = sort_by
            captured["sort_order"] = sort_order
            return ([], 0)

        with patch("infra.postgres.list_docs_paginated", side_effect=fake_paginated):
            client.get("/api/kb/kb1/docs?sort_by=title&sort_order=asc")

        assert captured["sort_by"] == "title"
        assert captured["sort_order"] == "asc"

    def test_doc_source_is_no_longer_valid_sort_field(self, client):
        """doc_source is not a valid sort field — should return 422."""
        resp = client.get("/api/kb/kb1/docs?sort_by=doc_source")
        assert resp.status_code == 422

    def test_invalid_sort_by_returns_422(self, client):
        resp = client.get("/api/kb/kb1/docs?sort_by=nonexistent_field")
        assert resp.status_code == 422

    def test_invalid_sort_order_returns_422(self, client):
        resp = client.get("/api/kb/kb1/docs?sort_order=sideways")
        assert resp.status_code == 422

    def test_sort_by_source_asc_in_store(self):
        from tests.conftest import FakePostgresStore

        store = FakePostgresStore()
        store.register_kb("kb1")
        store.create_doc("kb1", "zebra.pdf", "zebra.pdf", "s3", status="indexed")
        store.create_doc("kb1", "apple.pdf", "apple.pdf", "s3", status="indexed")
        store.create_doc("kb1", "mango.pdf", "mango.pdf", "s3", status="indexed")

        items, _ = store.list_docs_paginated("kb1", 1, 20, sort_by="title", sort_order="asc")
        sources = [d["title"] for d in items]
        assert sources == sorted(sources)

    def test_null_chunk_count_sorts_last_desc(self):
        from tests.conftest import FakePostgresStore

        store = FakePostgresStore()
        store.register_kb("kb1")
        doc_a = store.create_doc("kb1", "a.pdf", "a.pdf", "s3", status="indexed")
        doc_b = store.create_doc("kb1", "b.pdf", "b.pdf", "s3", status="indexed")  # chunk_count stays None
        doc_c = store.create_doc("kb1", "c.pdf", "c.pdf", "s3", status="indexed")
        store.update_doc_fields(doc_a["doc_id"], {"chunk_count": 50})
        store.update_doc_fields(doc_c["doc_id"], {"chunk_count": 10})

        items, _ = store.list_docs_paginated("kb1", 1, 20, sort_by="chunk_count", sort_order="desc")
        sources = [d["title"] for d in items]
        assert sources[-1] == "b.pdf"

    def test_null_chunk_count_sorts_last_asc(self):
        from tests.conftest import FakePostgresStore

        store = FakePostgresStore()
        store.register_kb("kb1")
        doc_a = store.create_doc("kb1", "a.pdf", "a.pdf", "s3", status="indexed")
        doc_b = store.create_doc("kb1", "b.pdf", "b.pdf", "s3", status="indexed")
        doc_c = store.create_doc("kb1", "c.pdf", "c.pdf", "s3", status="indexed")
        store.update_doc_fields(doc_a["doc_id"], {"chunk_count": 50})
        store.update_doc_fields(doc_c["doc_id"], {"chunk_count": 10})

        items, _ = store.list_docs_paginated("kb1", 1, 20, sort_by="chunk_count", sort_order="asc")
        sources = [d["title"] for d in items]
        assert sources[-1] == "b.pdf"


class TestListDocsItemShape:
    def test_item_fields_present(self, client):
        item = _make_doc("report.pdf")
        with patch("infra.postgres.list_docs_paginated", return_value=([item], 1)):
            resp = client.get("/api/kb/kb1/docs")

        doc = resp.json()["items"][0]
        assert "doc_id" in doc
        assert "title" in doc
        assert "status" in doc
        assert "doc_type" in doc
        assert "chunk_count" in doc
        assert "file_size" in doc
        assert "embedding_model" in doc
        assert "error" in doc
        assert "created_at" in doc
        assert "updated_at" in doc
