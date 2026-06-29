"""Dagster job for scheduled connector sync (R-12)."""

from __future__ import annotations

from dagster import in_process_executor, job

from rag_api.defs.ops.connector_sync_op import connector_sync_op


@job(
    description="Connector scheduled sync — triggered by per-connector Dagster Schedule.",
    tags={"pipeline": "connector_sync"},
    executor_def=in_process_executor,
)
def connector_sync_job():
    connector_sync_op()
