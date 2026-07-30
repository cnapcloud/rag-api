"""Unit tests for pipeline/steps/upsert.py — parent_chunks wiring
(docs/internal/design/parent-child-chunking.md §3.1)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from llama_index.core.schema import TextNode

from rag_api.pipeline.steps.chunk import ParentChunk
from rag_api.pipeline.steps.embed import EmbeddedNode
from rag_api.pipeline.steps.upsert import upsert

DOC_ID = "doc-abc"
KB_ID = "kb-01"

_DEL_PARENT_CHUNKS = "rag_api.infra.postgres.delete_parent_chunks_by_doc"
_SAVE_PARENT_CHUNKS = "rag_api.infra.postgres.save_parent_chunks"


def _embedded_node(parent_chunk_id: str | None = None) -> EmbeddedNode:
    node = TextNode(text="leaf text", metadata={"parent_chunk_id": parent_chunk_id})
    return EmbeddedNode(node=node, dense_vector=[0.1] * 4, sparse_indices=[0], sparse_values=[0.5])


def _parent_chunk(chunk_id="doc-abc:0") -> ParentChunk:
    return ParentChunk(
        chunk_id=chunk_id, level=0, parent_id=None, chunk_index=0, text="ancestor text",
        child_count=1, page_num=None, page_label=None,
    )


def test_upsert_replaces_parent_chunks_before_qdrant_leaf_upsert():
    """delete-then-insert must happen for Postgres ancestors before the Qdrant leaf swap, so a
    search landing mid-upsert never sees a leaf whose parent_chunk_id doesn't resolve yet."""
    call_order = []
    en = _embedded_node(parent_chunk_id="doc-abc:0")
    parents = [_parent_chunk()]

    with (
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.get_qdrant_client", return_value=MagicMock()),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.ensure_collection"),
        patch(
            "rag_api.pipeline.steps.upsert.qdrant_infra.delete_chunks_by_doc_id",
            side_effect=lambda *a, **k: call_order.append("qdrant_delete"),
        ),
        patch(
            "rag_api.pipeline.steps.upsert.qdrant_infra.upsert_chunks",
            side_effect=lambda *a, **k: call_order.append("qdrant_upsert"),
        ),
        patch(_DEL_PARENT_CHUNKS, side_effect=lambda doc_id: call_order.append("pg_delete_parents")),
        patch(_SAVE_PARENT_CHUNKS, side_effect=lambda doc_id, kb_id, p: call_order.append("pg_save_parents")),
    ):
        upsert(KB_ID, DOC_ID, [en], parents=parents)

    assert call_order.index("pg_delete_parents") < call_order.index("pg_save_parents")
    assert call_order.index("pg_save_parents") < call_order.index("qdrant_upsert")


def test_upsert_passes_doc_id_kb_id_and_parents_through():
    parents = [_parent_chunk()]

    with (
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.get_qdrant_client", return_value=MagicMock()),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.ensure_collection"),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.delete_chunks_by_doc_id"),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.upsert_chunks"),
        patch(_DEL_PARENT_CHUNKS) as mock_del,
        patch(_SAVE_PARENT_CHUNKS) as mock_save,
    ):
        upsert(KB_ID, DOC_ID, [_embedded_node()], parents=parents)

    mock_del.assert_called_once_with(DOC_ID)
    mock_save.assert_called_once_with(DOC_ID, KB_ID, parents)


def test_upsert_no_parents_is_still_replaced_with_empty_list():
    """Re-ingesting a doc that used to be hierarchical but no longer is (or a plain
    recursive/semantic doc) must clear any stale ancestor rows, not just skip touching them."""
    with (
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.get_qdrant_client", return_value=MagicMock()),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.ensure_collection"),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.delete_chunks_by_doc_id"),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.upsert_chunks"),
        patch(_DEL_PARENT_CHUNKS) as mock_del,
        patch(_SAVE_PARENT_CHUNKS) as mock_save,
    ):
        upsert(KB_ID, DOC_ID, [_embedded_node()])

    mock_del.assert_called_once_with(DOC_ID)
    mock_save.assert_called_once_with(DOC_ID, KB_ID, [])


def test_qdrant_payload_includes_parent_chunk_id_from_leaf_metadata():
    en = _embedded_node(parent_chunk_id="doc-abc:2")
    captured_points = []

    with (
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.get_qdrant_client", return_value=MagicMock()),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.ensure_collection"),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.delete_chunks_by_doc_id"),
        patch(
            "rag_api.pipeline.steps.upsert.qdrant_infra.upsert_chunks",
            side_effect=lambda kb, pts, client=None: captured_points.extend(pts),
        ),
        patch(_DEL_PARENT_CHUNKS),
        patch(_SAVE_PARENT_CHUNKS),
    ):
        upsert(KB_ID, DOC_ID, [en])

    assert captured_points[0].payload["parent_chunk_id"] == "doc-abc:2"


def test_qdrant_payload_parent_chunk_id_null_for_non_hierarchical_docs():
    en = _embedded_node(parent_chunk_id=None)
    captured_points = []

    with (
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.get_qdrant_client", return_value=MagicMock()),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.ensure_collection"),
        patch("rag_api.pipeline.steps.upsert.qdrant_infra.delete_chunks_by_doc_id"),
        patch(
            "rag_api.pipeline.steps.upsert.qdrant_infra.upsert_chunks",
            side_effect=lambda kb, pts, client=None: captured_points.extend(pts),
        ),
        patch(_DEL_PARENT_CHUNKS),
        patch(_SAVE_PARENT_CHUNKS),
    ):
        upsert(KB_ID, DOC_ID, [en])

    assert captured_points[0].payload["parent_chunk_id"] is None
