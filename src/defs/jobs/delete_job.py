"""delete_job — Qdrant 청크 삭제 → Redis 메타 삭제."""

from __future__ import annotations

from dagster import in_process_executor, job

from defs.ops.delete_ops import delete_chunks_op, delete_failure_hook, delete_meta_op, delete_s3_op


@job(
    description="Single document delete pipeline (one run per document)",
    tags={"pipeline": "delete"},
    hooks={delete_failure_hook},
    executor_def=in_process_executor,
)
def delete_job():
    result = delete_chunks_op()
    s3_result = delete_s3_op(result)
    delete_meta_op(s3_result)