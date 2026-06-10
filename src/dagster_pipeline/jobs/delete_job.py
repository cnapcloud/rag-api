"""delete_job — Qdrant 청크 삭제 → Redis 메타 삭제."""

from __future__ import annotations

from dagster import job

from dagster_pipeline.ops.delete_ops import delete_chunks_op, delete_failure_hook, delete_meta_op


@job(
    description="단일 문서 삭제 파이프라인 (문서 1개 = Run 1개)",
    tags={"pipeline": "delete"},
    hooks={delete_failure_hook},
)
def delete_job():
    result = delete_chunks_op()
    delete_meta_op(result)