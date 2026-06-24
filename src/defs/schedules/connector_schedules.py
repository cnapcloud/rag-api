"""Dynamic Dagster Schedule registration for connectors (R-12).

At startup, one ScheduleDefinition is created per connector with sync_schedule IS NOT NULL.
schedule_enabled is checked at execution time — toggling it requires no workspace reload.
Changing sync_schedule itself (the cron expression) requires a workspace reload.
"""

from __future__ import annotations

import logging

from dagster import RunRequest, ScheduleDefinition, SkipReason

from defs.jobs.connector_sync_job import connector_sync_job

logger = logging.getLogger(__name__)


def _make_connector_schedule(connector: dict) -> ScheduleDefinition:
    connector_id = connector["connector_id"]
    cron = connector["sync_schedule"]

    def execution_fn(context):
        from infra.postgres import get_connector

        c = get_connector(connector_id)
        if c is None:
            return SkipReason(f"Connector not found: {connector_id}")
        if not c.get("schedule_enabled"):
            return SkipReason(f"Schedule disabled: {connector_id}")
        if c.get("status") == "paused":
            return SkipReason(f"Connector paused: {connector_id}")

        return RunRequest(
            run_key=f"{connector_id}-{context.scheduled_execution_time.isoformat()}",
            run_config={"ops": {"connector_sync_op": {"config": {"connector_id": connector_id}}}},
            tags={"connector_id": connector_id, "trigger": "schedule"},
        )

    return ScheduleDefinition(
        name=f"connector_sync_{connector_id.replace('-', '_')}",
        cron_schedule=cron,
        job=connector_sync_job,
        execution_fn=execution_fn,
        description=f"Scheduled sync for connector {connector_id} ({cron})",
    )


def load_connector_schedules() -> list[ScheduleDefinition]:
    try:
        from infra.postgres import list_connectors

        connectors = list_connectors(has_schedule=True)
        schedules = [_make_connector_schedule(c) for c in connectors]
        logger.info("Loaded %d connector schedule(s) at startup", len(schedules))
        return schedules
    except Exception as e:
        logger.warning("Failed to load connector schedules at startup: %s", e)
        return []
