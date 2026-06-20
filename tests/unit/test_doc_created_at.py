"""Unit tests for US-10: doc_created_at extraction, upsert payload, meta storage, reindex ordering."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────
# _extract_doc_created_at
# ──────────────────────────────────────────────

class TestExtractDocCreatedAt:
    def _call(self, file_path, suffix, kb_id="kb-test", doc_source="doc.pdf"):
        from pipeline.ops.parse import _extract_doc_created_at
        return _extract_doc_created_at(file_path, suffix, kb_id, doc_source)

    def test_pdf_creation_date(self, tmp_path):
        """PDF with CreationDate returns that date as ISO UTC string."""
        import pypdf
        from pypdf import PdfWriter

        pdf_path = tmp_path / "test.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        dt = datetime(2023, 5, 15, 10, 30, 0, tzinfo=timezone.utc)
        writer.add_metadata({"/CreationDate": dt.strftime("D:%Y%m%d%H%M%SZ")})
        with open(pdf_path, "wb") as f:
            writer.write(f)

        result = self._call(pdf_path, ".pdf")
        assert "2023-05-15" in result

    def test_pdf_no_creation_date_falls_back_to_s3(self, tmp_path):
        """PDF without CreationDate falls back to S3 LastModified."""
        from pypdf import PdfWriter

        pdf_path = tmp_path / "test.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        with patch("infra.s3.get_object_last_modified", return_value="2024-01-01T00:00:00+00:00"):
            result = self._call(pdf_path, ".pdf")
        assert result == "2024-01-01T00:00:00+00:00"

    def test_docx_created_date(self, tmp_path):
        """DOCX with core_properties.created returns that date."""
        import docx

        docx_path = tmp_path / "test.docx"
        document = docx.Document()
        document.add_paragraph("Hello")
        document.save(str(docx_path))

        dt = datetime(2022, 3, 10, 8, 0, 0, tzinfo=timezone.utc)
        with patch("docx.Document") as mock_doc_cls:
            mock_doc = MagicMock()
            mock_doc.core_properties.created = dt
            mock_doc_cls.return_value = mock_doc
            result = self._call(docx_path, ".docx")

        assert "2022-03-10" in result

    def test_unsupported_type_falls_back_to_s3(self, tmp_path):
        """Non-PDF/DOCX file types fall back to S3 LastModified."""
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("hello")

        with patch("infra.s3.get_object_last_modified", return_value="2024-06-01T12:00:00+00:00"):
            result = self._call(txt_path, ".txt")
        assert result == "2024-06-01T12:00:00+00:00"

    def test_s3_fallback_failure_returns_empty(self, tmp_path):
        """If both extraction and S3 fallback fail, return empty string."""
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("hello")

        with patch("infra.s3.get_object_last_modified", side_effect=Exception("S3 error")):
            result = self._call(txt_path, ".txt")
        assert result == ""

    def test_naive_datetime_coerced_to_utc(self, tmp_path):
        """Naive datetime from PDF metadata is treated as UTC."""
        dt_naive = datetime(2021, 1, 1, 0, 0, 0)  # no tzinfo

        with patch("pypdf.PdfReader") as mock_reader_cls:
            mock_meta = MagicMock()
            mock_meta.creation_date = dt_naive
            mock_reader_cls.return_value.metadata = mock_meta

            pdf_path = tmp_path / "naive.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")  # minimal stub
            result = self._call(pdf_path, ".pdf")

        assert "+00:00" in result or "Z" in result
        assert "2021-01-01" in result


# ──────────────────────────────────────────────
# UpsertResult.doc_created_at + Qdrant payload
# ──────────────────────────────────────────────

class TestUpsertDocCreatedAt:
    def _make_embedded_node(self, doc_created_at: str = ""):
        from llama_index.core.schema import TextNode

        from pipeline.ops.embed import EmbeddedNode

        node = TextNode(text="sample chunk", metadata={"doc_created_at": doc_created_at})
        return EmbeddedNode(
            node=node,
            dense_vector=[0.1] * 4,
            sparse_indices=[0, 1],
            sparse_values=[0.5, 0.5],
        )

    def test_upsert_result_carries_doc_created_at(self, mock_qdrant):
        from pipeline.ops.upsert import upsert

        en = self._make_embedded_node("2023-05-15T10:30:00+00:00")
        with (
            patch("pipeline.ops.upsert.qdrant_infra.get_qdrant_client", return_value=mock_qdrant),
            patch("pipeline.ops.upsert.qdrant_infra.ensure_collection"),
            patch("pipeline.ops.upsert.qdrant_infra.delete_chunks_by_doc"),
            patch("pipeline.ops.upsert.qdrant_infra.upsert_chunks"),
        ):
            result = upsert("kb-test", "doc.pdf", [en])

        assert result.doc_created_at == "2023-05-15T10:30:00+00:00"

    def test_qdrant_payload_includes_doc_created_at(self, mock_qdrant):
        from pipeline.ops.upsert import upsert

        expected = "2023-05-15T10:30:00+00:00"
        en = self._make_embedded_node(expected)

        captured_points = []

        def capture_upsert(kb_id, points, client=None):
            captured_points.extend(points)

        with (
            patch("pipeline.ops.upsert.qdrant_infra.get_qdrant_client", return_value=mock_qdrant),
            patch("pipeline.ops.upsert.qdrant_infra.ensure_collection"),
            patch("pipeline.ops.upsert.qdrant_infra.delete_chunks_by_doc"),
            patch("pipeline.ops.upsert.qdrant_infra.upsert_chunks", side_effect=capture_upsert),
        ):
            upsert("kb-test", "doc.pdf", [en])

        assert len(captured_points) == 1
        assert captured_points[0].payload["doc_created_at"] == expected

    def test_empty_embedded_nodes_doc_created_at_is_empty(self, mock_qdrant):
        from pipeline.ops.upsert import upsert

        with (
            patch("pipeline.ops.upsert.qdrant_infra.get_qdrant_client", return_value=mock_qdrant),
            patch("pipeline.ops.upsert.qdrant_infra.ensure_collection"),
            patch("pipeline.ops.upsert.qdrant_infra.delete_chunks_by_doc"),
            patch("pipeline.ops.upsert.qdrant_infra.upsert_chunks"),
        ):
            result = upsert("kb-test", "doc.pdf", [])

        assert result.doc_created_at == ""


# ──────────────────────────────────────────────
# update_meta stores doc_created_at in Redis
# ──────────────────────────────────────────────

class TestMetaDocCreatedAt:
    def _make_upsert_result(self, doc_created_at="2023-05-15T10:30:00+00:00"):
        from pipeline.ops.upsert import UpsertResult

        return UpsertResult(
            kb_id="kb-test",
            doc_source="doc.pdf",
            chunk_count=3,
            doc_key="kb-test___doc.pdf",
            doc_created_at=doc_created_at,
        )

    def test_update_meta_stores_doc_created_at(self):
        from pipeline.ops.meta import update_meta

        stored: dict = {}

        def fake_set_doc_status(kb_id, doc_source, fields):
            stored.update(fields)

        with patch("pipeline.ops.meta.postgres_infra.set_doc_status", side_effect=fake_set_doc_status):
            update_meta(
                kb_id="kb-test",
                doc_source="doc.pdf",
                upsert_result=self._make_upsert_result("2023-05-15T10:30:00+00:00"),
                doc_created_at="2023-05-15T10:30:00+00:00",
            )

        assert stored.get("doc_created_at") == "2023-05-15T10:30:00+00:00"

    def test_update_meta_omits_doc_created_at_when_empty(self):
        from pipeline.ops.meta import update_meta

        stored: dict = {}

        def fake_set_doc_status(kb_id, doc_source, fields):
            stored.update(fields)

        with patch("pipeline.ops.meta.postgres_infra.set_doc_status", side_effect=fake_set_doc_status):
            update_meta(
                kb_id="kb-test",
                doc_source="doc.pdf",
                upsert_result=self._make_upsert_result(""),
                doc_created_at="",
            )

        assert "doc_created_at" not in stored


# ──────────────────────────────────────────────
# reindex_kb ordering
# ──────────────────────────────────────────────

class TestReindexOrdering:
    def test_reindex_ordered_by_doc_created_at_from_postgres(self):
        """Documents with Postgres doc_created_at are enqueued oldest-first."""
        objects = [
            ("c.pdf", "etag-c", "2024-03-01T00:00:00+00:00"),
            ("a.pdf", "etag-a", "2024-01-01T00:00:00+00:00"),
            ("b.pdf", "etag-b", "2024-02-01T00:00:00+00:00"),
        ]
        pg_docs = [
            {"doc_source": "a.pdf", "doc_created_at": "2022-06-01T00:00:00+00:00"},
            {"doc_source": "b.pdf", "doc_created_at": "2021-01-01T00:00:00+00:00"},
            {"doc_source": "c.pdf", "doc_created_at": "2023-01-01T00:00:00+00:00"},
        ]
        enqueued: list[str] = []

        def fake_trigger(kb_id, doc_source, etag, file_size, force=False):
            enqueued.append(doc_source)

        with (
            patch("infra.s3.list_kb_objects", return_value=objects),
            patch("infra.postgres.list_docs", return_value=pg_docs),
            patch("infra.postgres.get_doc_etag", return_value=None),
            patch("api.routers.docs._trigger_ingest", side_effect=fake_trigger),
        ):
            import asyncio
            from api.routers.docs import reindex_kb
            asyncio.run(reindex_kb(kb_id="kb-test", force=False))

        # b (2021) -> a (2022) -> c (2023)
        assert enqueued == ["b.pdf", "a.pdf", "c.pdf"]

    def test_reindex_fallback_to_s3_last_modified_when_no_postgres(self):
        """Documents without Postgres doc_created_at use S3 LastModified for ordering."""
        objects = [
            ("z.pdf", "etag-z", "2024-12-01T00:00:00+00:00"),
            ("m.pdf", "etag-m", "2024-06-01T00:00:00+00:00"),
            ("a.pdf", "etag-a", "2024-01-01T00:00:00+00:00"),
        ]
        enqueued: list[str] = []

        def fake_trigger(kb_id, doc_source, etag, file_size, force=False):
            enqueued.append(doc_source)

        with (
            patch("infra.s3.list_kb_objects", return_value=objects),
            patch("infra.postgres.list_docs", return_value=[]),
            patch("infra.postgres.get_doc_etag", return_value=None),
            patch("api.routers.docs._trigger_ingest", side_effect=fake_trigger),
        ):
            import asyncio
            from api.routers.docs import reindex_kb
            asyncio.run(reindex_kb(kb_id="kb-test", force=False))

        assert enqueued == ["a.pdf", "m.pdf", "z.pdf"]
