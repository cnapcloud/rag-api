"""Verdict-based post-processing for dedup results (identical / title_changed)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.ops.dedup.types import DedupResult

logger = logging.getLogger(__name__)


def _mark_dedup_skipped(
    doc_id: str,
    verdict: str,
    duplicate_doc_id: str | None,
    run_id: str,
) -> None:
    from infra.postgres import update_doc_fields

    note = f"dedup:{verdict}"
    if duplicate_doc_id:
        note += f" duplicate_of={duplicate_doc_id}"
    update_doc_fields(doc_id, {
        "status": "dedup_skipped",
        "error": note,
        "run_id": run_id,
        "process_finished_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info("Dedup skipped: doc_id=%s verdict=%s duplicate=%s", doc_id, verdict, duplicate_doc_id)


def handle_identical(doc_id: str, duplicate_doc_id: str | None, run_id: str = "") -> None:
    _mark_dedup_skipped(doc_id, "identical", duplicate_doc_id, run_id)


def handle_title_changed(doc_id: str, duplicate_doc_id: str | None, run_id: str = "") -> None:
    """Handle title_changed verdict.

    A newer than C: update C's Qdrant payload, mark C outdated, remove C from simhash_bands, mark A indexed.
    A older than C: mark A outdated only.
    """
    from infra.postgres import delete_simhash_bands, get_doc_by_id, update_doc_fields
    from infra.qdrant import update_payload_by_doc_id

    if not duplicate_doc_id:
        update_doc_fields(doc_id, {
            "status": "outdated",
            "error": "dedup:title_changed",
            "run_id": run_id,
            "process_finished_at": datetime.now(timezone.utc).isoformat(),
        })
        return

    doc_a = get_doc_by_id(doc_id)
    doc_c = get_doc_by_id(duplicate_doc_id)

    if doc_a is None or doc_c is None:
        logger.warning(
            "handle_title_changed: doc not found doc_a=%s doc_c=%s", doc_id, duplicate_doc_id
        )
        update_doc_fields(doc_id, {
            "status": "outdated",
            "error": f"dedup:title_changed duplicate_of={duplicate_doc_id}",
            "run_id": run_id,
            "process_finished_at": datetime.now(timezone.utc).isoformat(),
        })
        return

    created_a: datetime | None = doc_a.get("doc_created_at")
    created_c: datetime | None = doc_c.get("doc_created_at")
    a_is_newer = created_c is None or (created_a is not None and created_a > created_c)

    if a_is_newer:
        kb_id = doc_c.get("kb_id", "")
        update_payload_by_doc_id(kb_id, duplicate_doc_id, {
            "source": doc_a.get("source", ""),
            "source_uri": doc_a.get("source_uri", ""),
        })
        update_doc_fields(duplicate_doc_id, {"status": "outdated"})
        delete_simhash_bands(duplicate_doc_id)
        update_doc_fields(doc_id, {
            "status": "indexed",
            "run_id": run_id,
            "process_finished_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            "title_changed: A is newer, C outdated doc_a=%s doc_c=%s", doc_id, duplicate_doc_id,
        )
    else:
        update_doc_fields(doc_id, {
            "status": "outdated",
            "error": f"dedup:title_changed duplicate_of={duplicate_doc_id}",
            "run_id": run_id,
            "process_finished_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(
            "title_changed: A is older, no update doc_a=%s doc_c=%s", doc_id, duplicate_doc_id,
        )


def run_verdict(doc_id: str, result: DedupResult, run_id: str = "") -> None:
    """Persist detection hashes and dispatch verdict to handler."""
    from infra.postgres import update_doc_fields
    from pipeline.ops.dedup.simhash import u64_to_i64

    if result.title_hash:
        update_doc_fields(doc_id, {
            "title_hash": result.title_hash,
            "content_simhash": u64_to_i64(result.content_simhash),
        })

    if result.verdict == "identical":
        handle_identical(doc_id, result.duplicate_doc_id, run_id)
    elif result.verdict == "title_changed":
        handle_title_changed(doc_id, result.duplicate_doc_id, run_id)
    elif result.verdict != "proceed":
        logger.warning("run_verdict: unhandled verdict=%s doc_id=%s", result.verdict, doc_id)
