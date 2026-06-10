"""ingest_job — validate → parse → chunk → embed → upsert → meta."""

from __future__ import annotations

from dagster import job

from dagster_pipeline.ops.ingest_ops import (
    chunk_op,
    embed_op,
    ingest_failure_hook,
    meta_op,
    parse_op,
    upsert_op,
    validate_op,
)


@job(
    description="단일 문서 인제스트 파이프라인 (문서 1개 = Run 1개)",
    tags={"pipeline": "ingest"},
    hooks={ingest_failure_hook},
)
def ingest_job():
    valid_config = validate_op()
    docs = parse_op(valid_config)
    nodes = chunk_op(docs)
    vectors = embed_op(nodes)
    result = upsert_op(valid_config, vectors)
    meta_op(valid_config, result)