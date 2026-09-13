"""문서/KB 변경 시 검색 캐시 자동 무효화 단위 테스트 (US-53 F4)."""

from __future__ import annotations

from unittest.mock import patch

from rag_api.pipeline.steps.upsert import UpsertResult


class TestSetIndexedInvalidation:
    # AC: F4-1 (US-53-search-cache/T5)
    def test_set_indexed_invalidates_kb_cache(self) -> None:
        """문서가 indexed로 전이되면 해당 kb_id의 캐시를 무효화한다."""
        from rag_api.pipeline.utils.doc_state import set_indexed

        upsert_result = UpsertResult(kb_id="kb-x", doc_id="doc-1", chunk_count=3, doc_created_at="")

        with (
            patch("rag_api.infra.postgres.update_doc_fields"),
            patch("rag_api.query.search_cache.invalidate_kb_best_effort") as mock_invalidate,
        ):
            set_indexed("doc-1", upsert_result=upsert_result, kb_id="kb-x")

        mock_invalidate.assert_called_once_with("kb-x")

    def test_set_indexed_without_kb_id_skips_invalidation(self) -> None:
        """kb_id를 넘기지 않으면(기존 호출부와의 하위호환) 무효화를 시도하지 않는다."""
        from rag_api.pipeline.utils.doc_state import set_indexed

        upsert_result = UpsertResult(kb_id="kb-x", doc_id="doc-1", chunk_count=3, doc_created_at="")

        with (
            patch("rag_api.infra.postgres.update_doc_fields"),
            patch("rag_api.query.search_cache.invalidate_kb_best_effort") as mock_invalidate,
        ):
            set_indexed("doc-1", upsert_result=upsert_result)

        mock_invalidate.assert_not_called()

    def test_set_indexed_invalidation_failure_does_not_raise(self) -> None:
        """best-effort: invalidate_kb 실패(예: Redis 장애)해도 set_indexed는 정상 완료된다."""
        from rag_api.pipeline.utils.doc_state import set_indexed

        upsert_result = UpsertResult(kb_id="kb-x", doc_id="doc-1", chunk_count=3, doc_created_at="")

        with (
            patch("rag_api.infra.postgres.update_doc_fields"),
            patch("rag_api.query.search_cache.invalidate_kb", side_effect=RuntimeError("redis down")),
        ):
            set_indexed("doc-1", upsert_result=upsert_result, kb_id="kb-x")  # should not raise


class TestDeleteDocInvalidation:
    def _doc(self, status: str) -> dict:
        return {"doc_id": "doc-1", "kb_id": "kb-x", "status": status, "storage_key": "kb-x/doc.pdf"}

    # AC: F4-2 (US-53-search-cache/T5)
    def test_soft_delete_invalidates_kb_cache(self) -> None:
        """indexed 상태 문서를 soft delete하면 해당 kb_id의 캐시를 무효화한다."""
        from rag_api.pipeline.steps.delete import delete_doc

        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=self._doc("indexed")),
            patch("rag_api.pipeline.utils.doc_state.set_deleting"),
            patch("rag_api.infra.qdrant.delete_chunks_by_doc_id"),
            patch("rag_api.pipeline.utils.purge.purge_doc_artifacts"),
            patch("rag_api.infra.postgres.soft_delete_doc"),
            patch("rag_api.query.search_cache.invalidate_kb_best_effort") as mock_invalidate,
        ):
            delete_doc("doc-1")

        mock_invalidate.assert_called_once_with("kb-x")

    # AC: F4-2 (US-53-search-cache/T5)
    def test_hard_delete_invalidates_kb_cache(self) -> None:
        """non-indexed 상태 문서를 hard delete해도 해당 kb_id의 캐시를 무효화한다."""
        from rag_api.pipeline.steps.delete import delete_doc

        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=self._doc("failed")),
            patch("rag_api.pipeline.utils.doc_state.set_deleting"),
            patch("rag_api.infra.qdrant.delete_chunks_by_doc_id"),
            patch("rag_api.pipeline.utils.purge.purge_doc_artifacts"),
            patch("rag_api.infra.postgres.hard_delete_doc"),
            patch("rag_api.query.search_cache.invalidate_kb_best_effort") as mock_invalidate,
        ):
            delete_doc("doc-1")

        mock_invalidate.assert_called_once_with("kb-x")

    def test_invalidation_failure_does_not_block_delete(self) -> None:
        """best-effort: invalidate_kb 자체가 실패해도 delete_doc은 정상 완료된다."""
        from rag_api.pipeline.steps.delete import delete_doc

        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=self._doc("indexed")),
            patch("rag_api.pipeline.utils.doc_state.set_deleting"),
            patch("rag_api.infra.qdrant.delete_chunks_by_doc_id"),
            patch("rag_api.pipeline.utils.purge.purge_doc_artifacts"),
            patch("rag_api.infra.postgres.soft_delete_doc") as mock_soft_delete,
            patch("rag_api.query.search_cache.invalidate_kb", side_effect=RuntimeError("redis down")),
        ):
            delete_doc("doc-1")  # should not raise

        mock_soft_delete.assert_called_once_with("doc-1")

    def test_already_deleted_doc_skips_invalidation(self) -> None:
        """이미 deleted 상태인 문서는 삭제 로직 자체를 스킵하므로 캐시 무효화도 호출하지 않는다."""
        with (
            patch("rag_api.infra.postgres.get_doc_by_id", return_value=self._doc("deleted")),
            patch("rag_api.query.search_cache.invalidate_kb_best_effort") as mock_invalidate,
        ):
            from rag_api.pipeline.steps.delete import delete_doc

            delete_doc("doc-1")

        mock_invalidate.assert_not_called()
