"""ingest_job integration tests — execute_in_process."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

DOC_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def ingest_run_config():
    return {
        "ops": {
            "validate_op": {
                "config": {
                    "doc_id": DOC_ID,
                    "force": False,
                }
            }
        }
    }


@pytest.mark.skip(reason="Dagster integration environment required — infra mocks needed for CI")
def test_ingest_job_success(ingest_run_config):
    """ingest_job full flow integration test (requires infrastructure)."""
    from dagster import execute_in_process

    from rag_api.defs.jobs.ingest_job import ingest_job

    doc = {"doc_id": DOC_ID, "kb_id": "kb-test", "storage_key": "kb-test/test.pdf", "file_size": 1024, "status": "pending"}

    with (
        patch("rag_api.infra.postgres.get_doc_by_id", return_value=doc),
        patch("rag_api.infra.postgres.update_doc_fields"),
        patch("rag_api.pipeline.ops.parse.download_by_key"),
        patch("rag_api.pipeline.ops.parse.SimpleDirectoryReader") as mock_reader,
        patch("rag_api.pipeline.ops.embed.build_embed_model") as mock_embed,
        patch("rag_api.pipeline.ops.embed.build_sparse_model", return_value=None),
        patch("rag_api.infra.qdrant.get_qdrant_client") as mock_qdrant_client,
    ):
        from llama_index.core import Document
        mock_reader.return_value.load_data.return_value = [Document(text="test document content")]
        mock_embed.return_value.get_text_embedding_batch.return_value = [[0.1] * 1024]
        qdrant = MagicMock()
        qdrant.get_collection.side_effect = Exception("not found")
        mock_qdrant_client.return_value = qdrant

        result = execute_in_process(ingest_job, run_config=ingest_run_config)
        assert result.success


def test_ingest_job_validate_passes(ingest_run_config):
    """validate_op emits valid_config when doc exists and file size is within limits."""
    from rag_api.defs.jobs.ingest_job import ingest_job

    doc = {"doc_id": DOC_ID, "kb_id": "kb-test", "storage_key": "kb-test/test.pdf", "file_size": 1024, "status": "pending"}

    from rag_api.pipeline.ops.dedup.types import DedupResult

    with (
        patch("rag_api.infra.postgres.get_doc_by_id", return_value=doc),
        patch("rag_api.infra.postgres.update_doc_fields"),
        patch("rag_api.pipeline.ops.parse.parse", return_value=[]),
        patch("rag_api.pipeline.ops.dedup.run_simhash_detection",
              return_value=DedupResult(body_match="identical_level", needs_indexing=True)),
        patch("rag_api.pipeline.ops.dedup.run_verdict"),
        patch("rag_api.pipeline.ops.chunk.chunk", return_value=[MagicMock()]),
        patch("rag_api.pipeline.ops.embed.embed", return_value=[]),
        patch("rag_api.pipeline.ops.upsert.upsert") as mock_upsert,
        patch("rag_api.pipeline.ops.meta.set_indexed"),
    ):
        from rag_api.pipeline.ops.upsert import UpsertResult
        mock_upsert.return_value = UpsertResult(kb_id="kb-test", doc_id=DOC_ID, chunk_count=1, doc_created_at="")
        result = ingest_job.execute_in_process(run_config=ingest_run_config)
        assert result.success
