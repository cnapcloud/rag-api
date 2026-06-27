"""delete_job — document delete pipeline."""

from __future__ import annotations

from dagster import in_process_executor, job

from defs.ops.delete_ops import delete_failure_hook, delete_op


@job(
    description="Single document delete pipeline (one run per document)",
    tags={"pipeline": "delete"},
    hooks={delete_failure_hook},
    executor_def=in_process_executor,
)
def delete_job():
    delete_op()
