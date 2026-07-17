"""pipeline/steps/delete.py — pure delete function, status-based branching."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _delete_qdrant_chunks(kb_id: str, doc_id: str, status: str) -> None:
    """Remove Qdrant chunks. Propagates on indexed (soft delete must not fail);
    swallows on all other statuses (best-effort cleanup before hard delete)."""
    from rag_api.infra import qdrant as qdrant_infra

    if status == "indexed":
        qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id)
    else:
        try:
            qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id)
        except Exception as e:
            logger.warning("Qdrant chunk deletion failed (ignored): doc_id=%s err=%s", doc_id, e)


def _delete_db_record(
    doc_id: str,
    status: str,
    kb_id: str = "",
    storage_key: str = "",
    force: bool = False,
) -> None:
    """Persist delete in DB. indexed → soft delete unless force=True;
    all else → hard delete (bands + S3 purged via purge_doc_artifacts, then CASCADE removes DB row)."""
    from rag_api.infra.postgres import hard_delete_doc, soft_delete_doc
    from rag_api.pipeline.utils.purge import purge_doc_artifacts

    if status == "indexed" and not force:
        purge_doc_artifacts(doc_id, include_chunks=False)
        soft_delete_doc(doc_id)
    else:
        purge_doc_artifacts(doc_id, kb_id, storage_key, include_chunks=False)
        hard_delete_doc(doc_id)


def delete_doc(doc_id: str, run_id: str = "direct", force: bool = False) -> None:
    """Delete a document. Branches on status at call time:

    indexed + force=False → soft delete: Qdrant chunks removed, S3 kept, dedup bands removed, DB status='deleted'.
    indexed + force=True  → hard delete: same as all else.
    all else              → hard delete: Qdrant chunks attempted, S3 deleted, DB row removed.
    """
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.pipeline.utils.doc_state import set_deleting

    doc = get_doc_by_id(doc_id)
    if doc is None:
        logger.warning("delete_doc: doc not found doc_id=%s", doc_id)
        return

    status: str = doc.get("status", "")
    kb_id: str = doc["kb_id"]
    storage_key: str = doc.get("storage_key") or ""

    if status == "deleted":
        logger.info("delete_doc: already deleted, skip doc_id=%s", doc_id)
        return

    set_deleting(doc_id, run_id=run_id)

    _delete_qdrant_chunks(kb_id, doc_id, status)
    _delete_db_record(doc_id, status, kb_id=kb_id, storage_key=storage_key, force=force)

    is_hard = status != "indexed" or force
    if is_hard:
        logger.info("Hard delete done: doc_id=%s kb=%s status_was=%s force=%s", doc_id, kb_id, status, force)
    else:
        logger.info("Soft delete done: doc_id=%s kb=%s", doc_id, kb_id)
