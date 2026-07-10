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

_ACTIVE_RUNS_QUERY = """
query ActiveRuns($statuses: [RunStatus!]) {
  runsOrError(filter: {statuses: $statuses}) {
    __typename
    ... on Runs {
      results {
        runId
        tags { key value }
      }
    }
    ... on PythonError { message }
  }
}
"""

_ACTIVE_RUN_STATUSES = ["QUEUED", "STARTING", "STARTED", "CANCELING"]


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


def find_active_run_ids_by_doc_ids(doc_ids: list[str]) -> list[str]:
    """Find run_ids of active (QUEUED/STARTING/STARTED/CANCELING) runs tagged with any of doc_ids.

    Used to locate runs whose run_id has not yet been recorded in Postgres (the
    QUEUED/STARTING window before validate_op runs) so they can still be terminated.
    Returns [] on queue_worker mode, empty input, or GraphQL failure.
    """
    if not doc_ids:
        return []

    from rag_api.config.settings import get_settings
    cfg = get_settings()

    if cfg.queue_worker.enabled:
        logger.info("Queue worker mode: active run lookup skipped doc_ids=%s", doc_ids)
        return []

    import httpx

    url = f"{cfg.dagster.endpoint}/graphql"
    try:
        resp = httpx.post(
            url,
            json={"query": _ACTIVE_RUNS_QUERY, "variables": {"statuses": _ACTIVE_RUN_STATUSES}},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {}).get("runsOrError", {})
    except Exception as e:
        logger.warning("Dagster active run lookup failed (ignored): doc_ids=%s err=%s", doc_ids, e)
        return []

    typename = data.get("__typename", "")
    if typename != "Runs":
        logger.warning(
            "Dagster active run lookup unexpected response: type=%s msg=%s",
            typename, data.get("message", ""),
        )
        return []

    doc_id_set = set(doc_ids)
    run_ids = []
    for run in data.get("results", []):
        tags = {t["key"]: t["value"] for t in run.get("tags", [])}
        if tags.get("doc_id") in doc_id_set:
            run_ids.append(run["runId"])
    return run_ids
