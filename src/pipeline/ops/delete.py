"""pipeline/ops/delete.py — pure delete function, status-based branching."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _delete_qdrant_chunks(kb_id: str, doc_id: str, status: str) -> None:
    """Remove Qdrant chunks. Propagates on indexed (soft delete must not fail);
    swallows on all other statuses (best-effort cleanup before hard delete)."""
    from infra import qdrant as qdrant_infra

    if status == "indexed":
        qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id)
    else:
        try:
            qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id)
        except Exception as e:
            logger.warning("Qdrant chunk deletion failed (ignored): doc_id=%s err=%s", doc_id, e)


def _delete_s3_object(storage_key: str, doc_id: str, status: str) -> None:
    """Delete S3 object. Skipped for indexed (soft delete keeps S3);
    swallows ClientError on all other statuses."""
    if status == "indexed":
        return

    if not storage_key:
        return

    from botocore.exceptions import ClientError
    from infra.s3 import delete_by_key

    try:
        delete_by_key(storage_key)
    except ClientError as e:
        logger.warning("S3 deletion failed (ignored): doc_id=%s storage_key=%s err=%s", doc_id, storage_key, e)


def _delete_db_record(doc_id: str, status: str) -> None:
    """Persist delete in DB. indexed → soft delete (status='deleted') after clearing bands;
    all else → hard delete (CASCADE removes simhash_bands and minhash_bands)."""
    from infra.postgres import delete_minhash_bands, delete_simhash_bands, hard_delete_doc, soft_delete_doc

    if status == "indexed":
        delete_simhash_bands(doc_id)
        delete_minhash_bands(doc_id)
        soft_delete_doc(doc_id)
    else:
        hard_delete_doc(doc_id)


def delete_doc(doc_id: str, run_id: str = "direct") -> None:
    """Delete a document. Branches on status at call time:

    indexed  → soft delete: Qdrant chunks removed, S3 kept, dedup bands removed, DB status='deleted'.
    all else → hard delete: Qdrant chunks attempted, S3 deleted, DB row removed.
    """
    from infra.postgres import get_doc_by_id
    from pipeline.ops.meta import set_deleting

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
    _delete_s3_object(storage_key, doc_id, status)
    _delete_db_record(doc_id, status)

    if status == "indexed":
        logger.info("Soft delete done: doc_id=%s kb=%s", doc_id, kb_id)
    else:
        logger.info("Hard delete done: doc_id=%s kb=%s status_was=%s", doc_id, kb_id, status)
