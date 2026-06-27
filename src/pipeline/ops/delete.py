"""pipeline/ops/delete.py — pure delete function, status-based branching."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def delete_doc(doc_id: str, run_id: str = "direct") -> None:
    """Delete a document. Branches on status at call time:

    indexed  → soft delete: Qdrant chunks removed, S3 kept, DB status='deleted'.
    all else → hard delete: Qdrant chunks attempted, S3 deleted, DB row removed
               (CASCADE cleans simhash_bands and minhash_bands automatically).
    """
    from botocore.exceptions import ClientError
    from infra import qdrant as qdrant_infra
    from infra.postgres import get_doc_by_id, hard_delete_doc, soft_delete_doc
    from infra.s3 import delete_by_key
    from pipeline.ops.meta import set_deleting

    doc = get_doc_by_id(doc_id)
    if doc is None:
        logger.warning("delete_doc: doc not found doc_id=%s", doc_id)
        return

    status: str = doc.get("status", "")
    kb_id: str = doc["kb_id"]
    storage_key: str = doc.get("storage_key") or ""

    if status == "deleting":
        logger.info("delete_doc: already deleting, skip doc_id=%s", doc_id)
        return

    set_deleting(doc_id, run_id=run_id)

    if status == "indexed":
        qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id)
        soft_delete_doc(doc_id)
        logger.info("Soft delete done: doc_id=%s kb=%s", doc_id, kb_id)
    else:
        try:
            qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id)
        except Exception as e:
            logger.warning("Qdrant chunk deletion failed (ignored): doc_id=%s err=%s", doc_id, e)

        if storage_key:
            try:
                delete_by_key(storage_key)
            except ClientError as e:
                logger.warning("S3 deletion failed (ignored): doc_id=%s storage_key=%s err=%s", doc_id, storage_key, e)

        hard_delete_doc(doc_id)
        logger.info("Hard delete done: doc_id=%s kb=%s status_was=%s", doc_id, kb_id, status)
