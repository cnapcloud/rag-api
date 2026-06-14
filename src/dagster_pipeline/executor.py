"""Executor selection based on settings.dagster.executor."""

from __future__ import annotations

from dagster import ExecutorDefinition, in_process_executor

from config.settings import get_settings


def get_executor_def() -> ExecutorDefinition:
    mode = get_settings().dagster.executor
    if mode == "k8s":
        from dagster_k8s import k8s_job_executor  # type: ignore[import]

        return k8s_job_executor
    return in_process_executor
