"""pipeline/utils/abort_ingest.py — Abort in-flight ingest for a set of documents.

Used before a KB/connector is torn down (or a connector sync is aborted): terminates
any active Dagster run for each doc and clears both the main Redis queue and the delay
(retry) queue, so no queued event can later revive a document whose source content is
about to be removed. Must run before the caller purges S3/Qdrant content for these docs
-- otherwise a queued event that slips through can dispatch a pipeline run against
content that has already been deleted.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def abort_active_ingest(docs: list[dict]) -> tuple[int, int]:
    """Terminate active Dagster runs and clear queued events for the given docs.

    docs must be pending/running document rows (see
    get_active_ingest_docs_for_connector / get_active_ingest_docs_for_kb). Every doc is
    dequeued (both pending and running -- a running doc can still have a stale delayed
    retry event left over from an earlier blocked attempt) and marked failed("Aborted").

    Returns:
        (docs_aborted, runs_terminated)
    """
    from rag_api.infra.dagster_utils import find_active_run_ids_by_doc_ids, terminate_dagster_run
    from rag_api.pipeline.queue.enqueue import dequeue_upload_events
    from rag_api.pipeline.utils.doc_state import set_failed

    if not docs:
        return 0, 0

    for doc in docs:
        dequeue_upload_events(doc["doc_id"])

    running_docs = [d for d in docs if d["status"] == "running"]
    run_ids = {d["run_id"] for d in running_docs if d.get("run_id")}
    missing_run_doc_ids = [d["doc_id"] for d in running_docs if not d.get("run_id")]
    if missing_run_doc_ids:
        run_ids.update(find_active_run_ids_by_doc_ids(missing_run_doc_ids))

    for doc in docs:
        set_failed(doc["doc_id"], "Aborted")

    for run_id in run_ids:
        try:
            terminate_dagster_run(run_id)
        except RuntimeError as e:
            logger.warning("Dagster terminate failed (ignored): run_id=%s err=%s", run_id, e)

    logger.info("Active ingest aborted: docs=%d runs_terminated=%d", len(docs), len(run_ids))
    return len(docs), len(run_ids)
