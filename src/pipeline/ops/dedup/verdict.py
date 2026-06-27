"""Verdict-based post-processing for dedup results (identical / title_changed / similar)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pipeline.ops.dedup.types import DedupResult

logger = logging.getLogger(__name__)


def _resolve_newer(
    incoming_doc_id: str,
    existing_doc_id: str,
) -> tuple[dict | None, dict | None, Literal["incoming", "existing", "unknown"]]:
    """Fetch both docs and determine which is newer by doc_created_at.

    Returns (incoming_doc, existing_doc, winner) where winner is 'incoming' if the
    incoming doc is newer, 'existing' if the existing doc is newer, or 'unknown' if
    either doc is missing.
    """
    from infra.postgres import get_doc_by_id

    incoming_doc = get_doc_by_id(incoming_doc_id)
    existing_doc = get_doc_by_id(existing_doc_id)

    if incoming_doc is None or existing_doc is None:
        logger.warning(
            "_resolve_newer: doc not found incoming=%s existing=%s",
            incoming_doc_id,
            existing_doc_id,
        )
        return incoming_doc, existing_doc, "unknown"

    created_incoming: datetime | None = incoming_doc.get("doc_created_at")
    created_existing: datetime | None = existing_doc.get("doc_created_at")
    winner: Literal["incoming", "existing"] = (
        "incoming"
        if (created_existing is None or (created_incoming is not None and created_incoming > created_existing))
        else "existing"
    )
    return incoming_doc, existing_doc, winner


def _mark_outdated(
    doc_id: str,
    label: str,
    duplicate_doc_id: str | None,
) -> None:
    from infra.postgres import update_doc_fields

    update_doc_fields(doc_id, {
        "status": "outdated",
        "duplicate_of": duplicate_doc_id,
    })
    logger.info("Marked outdated: doc_id=%s verdict=%s duplicate=%s", doc_id, label, duplicate_doc_id)


def handle_identical(doc_id: str, duplicate_doc_id: str | None) -> None:
    _mark_outdated(doc_id, "identical", duplicate_doc_id)


def handle_title_changed(doc_id: str, duplicate_doc_id: str | None, run_id: str = "") -> None:
    """Title changed but body is identical.

    Incoming newer: update existing Qdrant payload, mark existing outdated,
    remove existing dedup bands, mark incoming indexed.
    Incoming older: mark incoming outdated only.
    """
    from infra.postgres import delete_minhash_bands, delete_simhash_bands, update_doc_fields
    from infra.qdrant import update_payload_by_doc_id

    if not duplicate_doc_id:
        _mark_outdated(doc_id, "title_changed", None)
        return

    incoming_doc, existing_doc, winner = _resolve_newer(doc_id, duplicate_doc_id)

    if winner != "incoming":
        _mark_outdated(doc_id, "title_changed", duplicate_doc_id)
        logger.info("title_changed: incoming older incoming=%s existing=%s", doc_id, duplicate_doc_id)
        return

    kb_id = existing_doc.get("kb_id", "")  # type: ignore[union-attr]
    update_payload_by_doc_id(kb_id, duplicate_doc_id, {
        "title": incoming_doc.get("title", ""),  # type: ignore[union-attr]
        "source": incoming_doc.get("source", ""),  # type: ignore[union-attr]
    })
    update_doc_fields(duplicate_doc_id, {
        "status": "outdated",
        "duplicate_of": doc_id,
        "run_id": run_id,
        "process_finished_at": datetime.now(timezone.utc).isoformat(),
    })
    delete_simhash_bands(duplicate_doc_id)
    delete_minhash_bands(duplicate_doc_id)
    update_doc_fields(doc_id, {
        "status": "indexed",
        "error": None,
        "run_id": run_id,
        "process_finished_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info("title_changed: incoming newer incoming=%s existing=%s", doc_id, duplicate_doc_id)


def handle_similar(doc_id: str, result: DedupResult, run_id: str = "") -> None:
    """Similar body. Newer document wins; older is marked outdated.

    Mutates result.needs_indexing: True if incoming wins and needs fresh vectors.
    When incoming wins, existing Qdrant chunks are deleted (body differs, no reuse possible).
    """
    from infra.postgres import delete_minhash_bands, delete_simhash_bands, update_doc_fields
    from infra.qdrant import delete_chunks_by_doc_id

    duplicate_doc_id = result.duplicate_doc_id
    if not duplicate_doc_id:
        _mark_outdated(doc_id, "similar", None)
        result.needs_indexing = False
        return

    _, existing_doc, winner = _resolve_newer(doc_id, duplicate_doc_id)

    if winner == "incoming":
        kb_id = existing_doc.get("kb_id", "")  # type: ignore[union-attr]
        delete_chunks_by_doc_id(kb_id, duplicate_doc_id)
        delete_simhash_bands(duplicate_doc_id)
        delete_minhash_bands(duplicate_doc_id)
        update_doc_fields(duplicate_doc_id, {
            "status": "outdated",
            "duplicate_of": doc_id,
            "run_id": run_id,
            "process_finished_at": datetime.now(timezone.utc).isoformat(),
        })
        result.needs_indexing = True
        logger.info("similar: incoming newer, existing chunks deleted incoming=%s existing=%s", doc_id, duplicate_doc_id)
    else:
        _mark_outdated(doc_id, "similar", duplicate_doc_id)
        result.needs_indexing = False
        logger.info("similar: incoming older incoming=%s existing=%s", doc_id, duplicate_doc_id)


def run_verdict(doc_id: str, result: DedupResult, run_id: str = "") -> None:
    """Apply post-processing based on body_match + title_match signals."""
    if result.candidate_doc_ids:
        logger.info(
            "run_verdict: doc_id=%s body_match=%s candidates=%s best_match=%s",
            doc_id, result.body_match, result.candidate_doc_ids, result.duplicate_doc_id,
        )
    match result.body_match:
        case "none":
            result.needs_indexing = True
        case "identical_level":
            if result.title_match == "changed":
                handle_title_changed(doc_id, result.duplicate_doc_id, run_id)
            else:
                handle_identical(doc_id, result.duplicate_doc_id)
        case "similar":
            handle_similar(doc_id, result, run_id)
        case _:
            logger.warning(
                "run_verdict: unhandled body_match=%s doc_id=%s", result.body_match, doc_id
            )
