"""purge_doc_artifacts — remove Qdrant chunks, S3 file, and dedup bands for a document."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def purge_doc_artifacts(
    doc_id: str,
    kb_id: str = "",
    storage_key: str = "",
    *,
    include_chunks: bool = True,
    swallow: bool = False,
) -> None:
    """Remove Qdrant chunks, S3 file, and dedup bands for a document.

    include_chunks: delete Qdrant vectors (skipped when kb_id is empty).
    storage_key: delete S3 file when non-empty. ClientError is always swallowed.
    swallow: when True, log warning on failure and continue; when False, propagate.
    """
    from rag_api.infra.postgres import (
        delete_minhash_bands,
        delete_parent_chunks_by_doc,
        delete_simhash_bands,
    )
    from rag_api.infra.qdrant import delete_chunks_by_doc_id

    def _run(fn, *args):
        if swallow:
            fn_name = getattr(fn, "__name__", repr(fn))
            try:
                fn(*args)
            except Exception as e:
                logger.warning(
                    "purge_doc_artifacts: %s failed (ignored): doc_id=%s err=%s",
                    fn_name, doc_id, e,
                )
        else:
            fn(*args)

    if include_chunks and kb_id:
        _run(delete_chunks_by_doc_id, kb_id, doc_id)

    if storage_key:
        from botocore.exceptions import ClientError

        from rag_api.infra.s3 import delete_by_key
        try:
            delete_by_key(storage_key)
        except ClientError as e:
            logger.warning("purge_doc_artifacts: S3 deletion failed (ignored): doc_id=%s err=%s", doc_id, e)

    _run(delete_simhash_bands, doc_id)
    _run(delete_minhash_bands, doc_id)
    _run(delete_parent_chunks_by_doc, doc_id)
