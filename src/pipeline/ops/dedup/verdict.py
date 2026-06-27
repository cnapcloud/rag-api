"""Verdict-based post-processing for dedup results (identical / title_changed / similar)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pipeline.ops.dedup.types import DedupResult

logger = logging.getLogger(__name__)


def _resolve_newer(
    doc_id_a: str,
    doc_id_c: str,
) -> tuple[dict | None, dict | None, Literal["a", "c", "unknown"]]:
    """Fetch both docs and determine which is newer by doc_created_at.

    Returns (doc_a, doc_c, winner) where winner is 'a' if incoming is newer,
    'c' if existing is newer, or 'unknown' if either doc is missing.
    """
    from infra.postgres import get_doc_by_id

    doc_a = get_doc_by_id(doc_id_a)
    doc_c = get_doc_by_id(doc_id_c)

    if doc_a is None or doc_c is None:
        logger.warning("_resolve_newer: doc not found a=%s c=%s", doc_id_a, doc_id_c)
        return doc_a, doc_c, "unknown"

    created_a: datetime | None = doc_a.get("doc_created_at")
    created_c: datetime | None = doc_c.get("doc_created_at")
    winner: Literal["a", "c"] = (
        "a" if (created_c is None or (created_a is not None and created_a > created_c)) else "c"
    )
    return doc_a, doc_c, winner


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
    remove existing simhash bands, mark incoming indexed.
    Incoming older: mark incoming outdated only.
    """
    from infra.postgres import delete_simhash_bands, update_doc_fields
    from infra.qdrant import update_payload_by_doc_id

    if not duplicate_doc_id:
        _mark_outdated(doc_id, "title_changed", None)
        return

    doc_a, doc_c, newer = _resolve_newer(doc_id, duplicate_doc_id)

    if newer != "a":
        _mark_outdated(doc_id, "title_changed", duplicate_doc_id)
        logger.info("title_changed: incoming older incoming=%s existing=%s", doc_id, duplicate_doc_id)
        return

    kb_id = doc_c.get("kb_id", "")  # type: ignore[union-attr]
    update_payload_by_doc_id(kb_id, duplicate_doc_id, {
        "source": doc_a.get("source", ""),  # type: ignore[union-attr]
        "source_uri": doc_a.get("source_uri", ""),  # type: ignore[union-attr]
    })
    update_doc_fields(duplicate_doc_id, {
        "status": "outdated",
        "duplicate_of": doc_id,
        "run_id": run_id,
        "process_finished_at": datetime.now(timezone.utc).isoformat(),
    })
    delete_simhash_bands(duplicate_doc_id)
    update_doc_fields(doc_id, {
        "status": "indexed",
        "run_id": run_id,
        "process_finished_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info("title_changed: incoming newer incoming=%s existing=%s", doc_id, duplicate_doc_id)


def handle_similar(doc_id: str, result: DedupResult, run_id: str = "") -> None:
    """Similar body. Newer document wins; older is marked outdated.

    Mutates result.needs_indexing: True if incoming wins and needs fresh vectors.
    When incoming wins, existing Qdrant chunks are deleted (body differs, no reuse possible).
    """
    from infra.postgres import update_doc_fields
    from infra.qdrant import delete_chunks_by_doc_id

    duplicate_doc_id = result.duplicate_doc_id
    if not duplicate_doc_id:
        _mark_outdated(doc_id, "similar", None)
        result.needs_indexing = False
        return

    _, doc_c, newer = _resolve_newer(doc_id, duplicate_doc_id)

    if newer == "a":
        kb_id = doc_c.get("kb_id", "")  # type: ignore[union-attr]
        delete_chunks_by_doc_id(kb_id, duplicate_doc_id)
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
