"""Dagster Definitions — 진입점.

실행:
    dagster dev -f src/dagster/definitions.py
"""

from __future__ import annotations

from dagster import Definitions

from rag_api.defs.jobs.connector_sync_job import connector_sync_job
from rag_api.defs.jobs.delete_job import delete_job
from rag_api.defs.jobs.ingest_job import ingest_job
from rag_api.defs.resources.resources import build_resources_from_settings
from rag_api.defs.schedules.connector_schedules import load_connector_schedules
from rag_api.defs.sensors.event_queue_sensor import event_queue_sensor

defs = Definitions(
    jobs=[ingest_job, delete_job, connector_sync_job],
    sensors=[event_queue_sensor],
    schedules=load_connector_schedules(),
    resources=build_resources_from_settings(),
)