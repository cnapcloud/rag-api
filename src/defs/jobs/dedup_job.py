"""dedup_job — standalone dedup pipeline for backfill and manual re-processing.

Pipeline: simhash_op -> verdict_op
  simhash_op downloads the document from MinIO directly.

Not triggered by sensor or schedule. Run manually or from a backfill script.
Shares the same pure functions as run_dedup_pipeline() used in ingest_job.
"""

from __future__ import annotations

from dagster import in_process_executor, job

from defs.ops.dedup_ops import simhash_op, verdict_op
from defs.ops.ingest_ops import ingest_failure_hook


@job(
    description="Standalone dedup pipeline — stage 1 (SimHash) for backfill / manual re-processing",
    tags={"pipeline": "dedup"},
    hooks={ingest_failure_hook},
    executor_def=in_process_executor,
)
def dedup_job():
    simhash_result = simhash_op()
    verdict_op(simhash_result)
