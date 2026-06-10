"""ingest_job 통합 테스트 — execute_in_process."""

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
                    "object_key": "pdf/test.pdf",
                    "etag": "test-etag-001",
                    "file_size": 1024,
                }
            }
        }
    }


@pytest.mark.skip(reason="Dagster 통합 환경 필요 — CI에서는 인프라 Mock 필요")
def test_ingest_job_success(ingest_run_config):
    """ingest_job 전체 흐름 통합 테스트 (인프라 필요)."""
    from dagster import execute_in_process

    from dagster_pipeline.jobs.ingest_job import ingest_job

    with (
        patch("dagster.ops.validate.redis_infra.get_doc_etag", return_value=None),
        patch("dagster.ops.parse.download_object"),
        patch("dagster.ops.parse.SimpleDirectoryReader") as mock_reader,
        patch("dagster.ops.embed.build_embed_model") as mock_embed,
        patch("dagster.ops.embed.build_sparse_model", return_value=None),
        patch("dagster.infra.qdrant.get_qdrant_client") as mock_qdrant_client,
        patch("dagster.infra.redis.get_redis_client") as mock_redis_client,
    ):
        from llama_index.core import Document
        from llama_index.core.schema import TextNode

        mock_reader.return_value.load_data.return_value = [Document(text="테스트 문서 내용")]
        mock_embed.return_value.get_text_embedding_batch.return_value = [[0.1] * 1024]

        qdrant = MagicMock()
        qdrant.get_collection.side_effect = Exception("not found")
        mock_qdrant_client.return_value = qdrant

        redis = MagicMock()
        redis.hget.return_value = None
        mock_redis_client.return_value = redis

        result = execute_in_process(ingest_job, run_config=ingest_run_config)
        assert result.success


def test_ingest_job_skips_on_same_etag(ingest_run_config):
    """ETag 동일 시 validate_op에서 스킵하여 파이프라인이 조기 종료된다."""
    from dagster_pipeline.jobs.ingest_job import ingest_job

    with (
        patch("pipeline.ops.validate.redis_infra.get_doc_status", return_value=None),
        patch("pipeline.ops.validate.redis_infra.get_doc_etag", return_value="test-etag-001"),
        patch("pipeline.ops.meta.redis_infra.set_doc_status"),
    ):
        result = ingest_job.execute_in_process(run_config=ingest_run_config)
        # validate_op이 Output을 발행하지 않아 후속 Op이 스킵되어도 job은 success
        assert result.success