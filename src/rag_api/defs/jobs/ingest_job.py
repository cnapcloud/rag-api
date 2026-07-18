"""ingest_job — validate → parse → dedup → chunk → embed → upsert → meta."""

from __future__ import annotations

from dagster import in_process_executor, job

from rag_api.defs.ops.ingest_ops import (
    chunk_op,
    dedup_op,
    embed_op,
    ingest_failure_hook,
    meta_op,
    parse_op,
    upsert_op,
    validate_op,
)


@job(
    description="Single document ingest pipeline (one run per document)",
    tags={"pipeline": "ingest"},
    hooks={ingest_failure_hook},
    executor_def=in_process_executor,
)
def ingest_job():
    valid_config = validate_op()
    documents = parse_op(valid_config)
    to_chunk = dedup_op(valid_config, documents)
    nodes = chunk_op(valid_config, to_chunk)
    vectors = embed_op(nodes)
    result = upsert_op(valid_config, vectors)
    meta_op(valid_config, result)
