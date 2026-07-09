"""dedup_job — standalone dedup pipeline for backfill and manual re-processing.

Pipeline: parse_op -> simhash_op -> minhash_op -> chunk_compare_op -> verdict_op

Not triggered by sensor or schedule. Run manually or from a backfill script.
Triggered externally by passing doc_id via run config (ops.parse_op.config.doc_id).
"""

from __future__ import annotations

from dagster import in_process_executor, job

from rag_api.defs.ops.dedup_ops import (
    chunk_compare_op,
    minhash_op,
    parse_op,
    simhash_op,
    verdict_op,
)
from rag_api.defs.ops.ingest_ops import ingest_failure_hook


@job(
    description=(
        "Standalone dedup pipeline — parse -> simhash -> minhash -> chunk_compare -> verdict"
        " for backfill / manual re-processing"
    ),
    tags={"pipeline": "dedup"},
    hooks={ingest_failure_hook},
    executor_def=in_process_executor,
)
def dedup_job():
    parsed = parse_op()
    simhash_result = simhash_op(parsed.valid_config, parsed.documents)
    minhash_result = minhash_op(parsed.valid_config, parsed.documents, simhash_result)
    chunk_compare_result = chunk_compare_op(parsed.valid_config, parsed.documents, minhash_result)
    verdict_op(parsed.valid_config, chunk_compare_result)
