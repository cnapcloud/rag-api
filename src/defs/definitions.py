"""Dagster Definitions — 진입점.

실행:
    dagster dev -f src/dagster/definitions.py
"""

from __future__ import annotations

from dagster import Definitions

from defs.jobs.delete_job import delete_job
from defs.jobs.ingest_job import ingest_job
from defs.resources.resources import build_resources_from_settings
from defs.sensors.event_queue_sensor import event_queue_sensor

defs = Definitions(
    jobs=[ingest_job, delete_job],
    sensors=[event_queue_sensor],
    resources=build_resources_from_settings(),
)