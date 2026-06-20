"""ingest_job integration tests — execute_in_process."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def ingest_run_config():
    return {
        "ops": {
            "validate_op": {
                "config": {
                    "kb_id": "kb-test",
                    "doc_source": "pdf/test.pdf",
                    "etag": "test-etag-001",
                    "file_size": 1024,
                }
            }
        }
    }


@pytest.mark.skip(reason="Dagster integration environment required — infra mocks needed for CI")
def test_ingest_job_success(ingest_run_config):
    """ingest_job full flow integration test (requires infrastructure)."""
    from dagster import execute_in_process

    from dagster_pipeline.jobs.ingest_job import ingest_job

    with (
        patch("pipeline.ops.validate.postgres_infra.get_doc_etag", return_value=None),
        patch("dagster.ops.parse.download_object"),
        patch("dagster.ops.parse.SimpleDirectoryReader") as mock_reader,
        patch("dagster.ops.embed.build_embed_model") as mock_embed,
        patch("dagster.ops.embed.build_sparse_model", return_value=None),
        patch("dagster.infra.qdrant.get_qdrant_client") as mock_qdrant_client,
        patch("infra.postgres.get_doc_status", return_value=None),
    ):
        from llama_index.core import Document

        mock_reader.return_value.load_data.return_value = [Document(text="test document content")]
        mock_embed.return_value.get_text_embedding_batch.return_value = [[0.1] * 1024]

        qdrant = MagicMock()
        qdrant.get_collection.side_effect = Exception("not found")
        mock_qdrant_client.return_value = qdrant

        result = execute_in_process(ingest_job, run_config=ingest_run_config)
        assert result.success


def test_ingest_job_skips_on_same_etag(ingest_run_config):
    """ETag unchanged -> validate_op skips and pipeline exits early."""
    from dagster_pipeline.jobs.ingest_job import ingest_job

    with (
        patch("infra.postgres.get_doc_status", return_value=None),
        patch("infra.postgres.set_doc_status"),
        patch("pipeline.ops.validate.postgres_infra.get_doc_etag", return_value="test-etag-001"),
        patch("infra.redis.get_redis_client", return_value=MagicMock()),
    ):
        result = ingest_job.execute_in_process(run_config=ingest_run_config)
        # validate_op emits no Output so downstream ops are skipped, but job succeeds
        assert result.success
