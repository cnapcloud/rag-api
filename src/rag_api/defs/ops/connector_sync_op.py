"""Dagster op for scheduled connector sync (R-12)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from dagster import op

logger = logging.getLogger(__name__)

_STALE_SYNC_TIMEOUT_SEC = 3600


@op(config_schema={"connector_id": str})
def connector_sync_op(context) -> None:
    from rag_api.api.routers.connectors import _dispatch_sync
    from rag_api.infra.postgres import get_connector, set_connector_status, set_connector_sync_status

    connector_id = context.op_config["connector_id"]
    connector = get_connector(connector_id)

    if connector is None:
        context.log.warning("Connector not found, skipping scheduled sync: connector_id=%s", connector_id)
        return

    if connector["status"] == "paused":
        context.log.info("Connector paused, skipping scheduled sync: connector_id=%s", connector_id)
        return

    if connector["sync_status"] == "running":
        sync_started_at_str = connector.get("sync_started_at")
        if sync_started_at_str:
            started_at = datetime.fromisoformat(sync_started_at_str).astimezone(timezone.utc)
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            if elapsed < _STALE_SYNC_TIMEOUT_SEC:
                context.log.info(
                    "Sync already running, skipping scheduled sync: connector_id=%s", connector_id
                )
                return
            context.log.warning(
                "Stale sync lock detected, proceeding: connector_id=%s elapsed=%ds",
                connector_id,
                int(elapsed),
            )

    set_connector_sync_status(connector_id, "running")
    try:
        _dispatch_sync(connector)
        set_connector_status(connector_id, "active")
        set_connector_sync_status(connector_id, "idle", last_synced_at=datetime.now(timezone.utc))
        context.log.info("Scheduled connector sync complete: connector_id=%s", connector_id)
    except Exception as e:
        set_connector_status(connector_id, "error", error=str(e))
        set_connector_sync_status(connector_id, "idle")
        context.log.error("Scheduled connector sync failed: connector_id=%s err=%s", connector_id, e)
        raise
