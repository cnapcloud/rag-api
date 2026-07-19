"""pipeline/runner.py — Run a single-document pipeline without Dagster."""

from __future__ import annotations

import logging

from rag_api.config.settings import get_settings

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
    from rag_api.exceptions import IngestValidationError
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.pipeline.steps.chunk import chunk
    from rag_api.pipeline.steps.embed import embed
    from rag_api.pipeline.steps.meta import set_indexed
    from rag_api.pipeline.steps.parse import parse
    from rag_api.pipeline.steps.upsert import upsert
    from rag_api.pipeline.steps.validate import validate
    from rag_api.pipeline.utils.doc_state import set_failed, set_processing

    doc = get_doc_by_id(doc_id)
    if doc is None:
        raise IngestValidationError(f"Document not found: doc_id={doc_id}")

    kb_id: str = doc["kb_id"]
    storage_key: str = doc.get("storage_key") or ""
    title: str = doc.get("title") or ""
    source_type: str = doc.get("source_type") or ""
    source: str = doc.get("source") or ""

    try:
        validate(doc_id, force=force)
    except IngestValidationError as e:
        set_failed(doc_id, str(e), run_id=run_id)
        logger.error("Validation failed: doc_id=%s err=%s", doc_id, e)
        raise

    set_processing(doc_id, run_id=run_id)

    try:
        from rag_api.infra.postgres import update_doc_fields
        from rag_api.pipeline.steps.dedup import run_dedup_pipeline

        documents = parse(doc_id=doc_id, kb_id=kb_id, storage_key=storage_key)

        if documents:
            doc_created_at = documents[0].metadata.get("doc_created_at", "")
            if doc_created_at:
                update_doc_fields(doc_id, {"doc_created_at": doc_created_at})

        dedup_result = run_dedup_pipeline(doc_id=doc_id, kb_id=kb_id, run_id=run_id, documents=documents)
        if not dedup_result.needs_indexing:
            logger.info(
                "Dedup skipped indexing: doc_id=%s body_match=%s duplicate=%s",
                doc_id, dedup_result.body_match, dedup_result.duplicate_doc_id,
            )
            return 0

        nodes = chunk(documents, kb_id=kb_id)
        if not nodes:
            raise IngestValidationError("No indexable content: all chunks below min_chunk_chars threshold")
        embedded_nodes = embed(nodes)
        upsert_result = upsert(
            kb_id, doc_id, embedded_nodes,
            title=title, source_type=source_type, source=source,
        )

        cfg = get_settings().embedding
        doc_type = storage_key.rsplit(".", 1)[-1] if "." in storage_key else ""
        set_indexed(
            doc_id=doc_id,
            upsert_result=upsert_result,
            run_id=run_id,
            doc_type=doc_type,
            embedding_model=cfg.model,
        )
        logger.info("Ingest done: doc_id=%s kb=%s chunks=%d", doc_id, kb_id, upsert_result.chunk_count)
        return upsert_result.chunk_count

    except Exception as e:
        set_failed(doc_id, str(e), run_id=run_id)
        logger.exception("Pipeline failed: doc_id=%s kb=%s", doc_id, kb_id)
        raise


def run_delete_pipeline(doc_id: str, force: bool = False) -> None:
    """Delete a document. Delegates to delete_doc() for status-based soft/hard delete logic."""
    from rag_api.pipeline.steps.delete import delete_doc
    from rag_api.pipeline.utils.doc_state import set_failed

    try:
        delete_doc(doc_id, run_id="direct", force=force)
    except Exception as e:
        set_failed(doc_id, f"delete_pipeline failed: {e}")
        logger.exception("Delete pipeline failed: doc_id=%s", doc_id)
        raise
