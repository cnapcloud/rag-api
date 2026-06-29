"""infra/dagster_utils.py — Dagster remote control via GraphQL API."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_RELOAD_MUTATION = """
mutation {
  reloadWorkspace {
    __typename
    ... on Workspace { locationEntries { name loadStatus } }
    ... on PythonError { message }
  }
}
"""

_TERMINATE_MUTATION = """
mutation TerminateRun($runId: String!) {
  terminateRun(runId: $runId, terminatePolicy: MARK_AS_CANCELED_IMMEDIATELY) {
    __typename
    ... on TerminateRunSuccess { run { runId } }
    ... on TerminateRunFailure { message }
    ... on RunNotFoundError { runId }
  }
}
"""


def reload_code_location() -> None:
    """Reload all Dagster workspace locations to pick up connector schedule changes.

    Non-fatal: logs warning on failure. No-op in queue_worker mode.
    """
    from rag_api.config.settings import get_settings
    cfg = get_settings()

    if cfg.queue_worker.enabled:
        logger.info("Queue worker mode: Dagster reload skipped")
        return

    import httpx

    url = f"{cfg.dagster.endpoint}/graphql"
    try:
        resp = httpx.post(url, json={"query": _RELOAD_MUTATION}, timeout=10.0)
        resp.raise_for_status()
        data = resp.json().get("data", {}).get("reloadWorkspace", {})
        typename = data.get("__typename", "")
        if typename == "Workspace":
            entries = data.get("locationEntries", [])
            logger.info(
                "Dagster workspace reloaded: locations=%s",
                [e["name"] for e in entries],
            )
        else:
            logger.warning(
                "Dagster workspace reload unexpected response: type=%s msg=%s",
                typename, data.get("message", ""),
            )
    except Exception as e:
        logger.warning("Dagster workspace reload failed (ignored): err=%s", e)


def terminate_dagster_run(run_id: str) -> None:
    """Force-terminate a Dagster run via GraphQL API.

    No-op if run is not found or already finished.
    Raises RuntimeError if the run is active but termination fails.
    """
    from rag_api.config.settings import get_settings
    cfg = get_settings()

    if cfg.queue_worker.enabled:
        logger.info("Queue worker mode: Dagster terminate skipped run_id=%s", run_id)
        return

    import httpx

    url = f"{cfg.dagster.endpoint}/graphql"
    resp = httpx.post(
        url,
        json={"query": _TERMINATE_MUTATION, "variables": {"runId": run_id}},
        timeout=5.0,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {}).get("terminateRun", {})
    typename = data.get("__typename", "")
    if typename == "TerminateRunSuccess":
        logger.info("Dagster run force-terminated: run_id=%s", run_id)
        return
    if typename == "RunNotFoundError":
        logger.info("Dagster run not found (already finished): run_id=%s", run_id)
        return
    message = data.get("message", typename)
    if typename == "TerminateRunFailure" and "having status" in message:
        logger.info("Dagster run already in terminal state (skipping): run_id=%s reason=%s", run_id, message)
        return
    raise RuntimeError(
        f"Dagster force-terminate failed: run_id={run_id} reason={message}"
    )
