"""pipeline/runner.py — Run a single-document pipeline without Dagster."""

from __future__ import annotations

import logging

from config.settings import get_settings

logger = logging.getLogger(__name__)


def run_ingest_pipeline(
    doc_id: str,
    force: bool = False,
    run_id: str = "direct",
) -> int:
    """Run the ingest pipeline for a document identified by doc_id.

    Looks up doc row to get kb_id and storage_key, then runs validate->parse->chunk->embed->upsert->meta.
    Returns chunk_count on success.
    """
    from exceptions import IngestValidationError
    from infra.postgres import get_doc_by_id
    from pipeline.ops.chunk import chunk
    from pipeline.ops.embed import embed
    from pipeline.ops.meta import restore_indexed, set_failed, set_processing, update_meta
    from pipeline.ops.parse import parse
    from pipeline.ops.upsert import upsert
    from pipeline.ops.validate import validate

    doc = get_doc_by_id(doc_id)
    if doc is None:
        raise IngestValidationError(f"Document not found: doc_id={doc_id}")

    kb_id: str = doc["kb_id"]
    storage_key: str = doc.get("storage_key") or ""
    source: str = doc.get("source") or ""
    source_type: str = doc.get("source_type") or ""
    source_uri: str = doc.get("source_uri") or ""

    try:
        validate(doc_id, force=force)
    except IngestValidationError as e:
        set_failed(doc_id, str(e), run_id=run_id)
        logger.error("Validation failed: doc_id=%s err=%s", doc_id, e)
        raise

    set_processing(doc_id, run_id=run_id)

    try:
        from pipeline.ops.dedup import run_dedup_pipeline
        dedup_result = run_dedup_pipeline(doc_id=doc_id, run_id=run_id)
        if not dedup_result.needs_indexing:
            logger.info("Dedup skipped indexing: doc_id=%s verdict=%s", doc_id, dedup_result.verdict)
            return 0

        documents = parse(doc_id=doc_id, storage_key=storage_key)
        nodes = chunk(documents)
        if not nodes:
            raise IngestValidationError("No indexable content: all chunks below min_chunk_chars threshold")
        embedded_nodes = embed(nodes)
        upsert_result = upsert(
            kb_id, doc_id, embedded_nodes,
            source=source, source_type=source_type, source_uri=source_uri,
        )

        cfg = get_settings().embedding
        doc_type = storage_key.rsplit(".", 1)[-1] if "." in storage_key else ""
        update_meta(
            doc_id=doc_id,
            upsert_result=upsert_result,
            run_id=run_id,
            doc_type=doc_type,
            embedding_model=cfg.model,
            doc_created_at=upsert_result.doc_created_at,
        )
        logger.info("Ingest done: doc_id=%s kb=%s chunks=%d", doc_id, kb_id, upsert_result.chunk_count)
        return upsert_result.chunk_count

    except Exception as e:
        set_failed(doc_id, str(e), run_id=run_id)
        logger.exception("Pipeline failed: doc_id=%s kb=%s", doc_id, kb_id)
        raise


def run_delete_pipeline(doc_id: str) -> None:
    """Delete a document's Qdrant chunks, S3 object, and soft-delete its Postgres row."""
    from botocore.exceptions import ClientError
    from infra import qdrant as qdrant_infra
    from infra.postgres import get_doc_by_id, soft_delete_doc
    from infra.s3 import delete_by_key
    from pipeline.ops.meta import set_deleting, set_failed

    doc = get_doc_by_id(doc_id)
    if doc is None:
        logger.warning("run_delete_pipeline: doc not found: doc_id=%s", doc_id)
        return

    kb_id: str = doc["kb_id"]
    set_deleting(doc_id, run_id="direct")
    try:
        qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id)
        soft_delete_doc(doc_id)

        storage_key = doc.get("storage_key") or ""
        if storage_key:
            try:
                delete_by_key(storage_key)
            except ClientError as e:
                logger.warning(
                    "S3 object deletion failed (ignored): doc_id=%s storage_key=%s err=%s",
                    doc_id, storage_key, e,
                )

        logger.info("Delete done: doc_id=%s kb=%s", doc_id, kb_id)
    except Exception as e:
        set_failed(doc_id, f"delete_pipeline failed: {e}")
        logger.exception("Delete pipeline failed: doc_id=%s kb=%s", doc_id, kb_id)
        raise
