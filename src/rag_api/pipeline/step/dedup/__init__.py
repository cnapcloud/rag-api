"""Dedup pipeline — simhash + minhash/pg_trgm + chunk_compare detection steps."""

from __future__ import annotations

import logging

from rag_api.pipeline.step.dedup.chunk_compare import run_chunk_compare
from rag_api.pipeline.step.dedup.simhash import run_simhash_detection
from rag_api.pipeline.step.dedup.types import BodyMatch, DedupResult, TitleMatch
from rag_api.pipeline.step.dedup.verdict import run_verdict
from rag_api.pipeline.step.parser.extensions import DOCUMENT_EXTENSIONS

logger = logging.getLogger(__name__)

__all__ = ["run_dedup_pipeline", "run_simhash_detection", "run_chunk_compare", "run_verdict",
           "DedupResult", "BodyMatch", "TitleMatch", "is_document"]


def is_document(documents) -> bool:
    """True if the parsed doc's file type belongs to the 'documents' category.

    Dedup (SimHash/MinHash near-duplicate detection) is meaningful for prose
    content only; source code and config/data files are excluded.
    """
    if not documents:
        return True
    doc_type = documents[0].metadata.get("doc_type", "")
    return f".{doc_type}" in DOCUMENT_EXTENSIONS


def run_dedup_pipeline(
    doc_id: str,
    kb_id: str = "",
    run_id: str = "direct",
    documents=None,
) -> DedupResult:
    """Run the full dedup pipeline for a single document (runner.py / non-Dagster path).

    simhash step: detects body similarity level and title match via Hamming distance.
    minhash step: runs only when the simhash step's body_match is 'none'; detects
    similar documents by Jaccard score and title fuzzy similarity.
    chunk_compare step: runs only when the simhash/minhash step's body_match is 'similar';
    confirms body_match (identical_level/similar/none) via chunk-level embedding comparison.

    Returns DedupResult; caller uses needs_indexing to decide whether to proceed to
    chunk/embed/upsert.
    """
    from rag_api.config.settings import get_settings

    cfg = get_settings()
    if not cfg.dedup.enabled:
        logger.info("Dedup disabled: doc_id=%s", doc_id)
        return DedupResult(body_match="none", needs_indexing=True)

    if documents is None:
        from rag_api.exceptions import IngestValidationError
        from rag_api.infra.postgres import get_doc_by_id
        from rag_api.pipeline.step.parse import parse

        doc = get_doc_by_id(doc_id)
        if doc is None:
            raise IngestValidationError(f"Document not found: doc_id={doc_id}")
        documents = parse(doc_id=doc_id, storage_key=doc.get("storage_key", ""))

    if not is_document(documents):
        doc_type = documents[0].metadata.get("doc_type", "") if documents else ""
        logger.info("Dedup skipped (non-document type=%s): doc_id=%s", doc_type, doc_id)
        return DedupResult(needs_indexing=True)

    title = " ".join(d.metadata.get("file_name", "") for d in documents[:1])
    body = " ".join(d.text for d in documents)

    # simhash step
    result = run_simhash_detection(
        doc_id=doc_id,
        title=title,
        body=body,
        cfg=cfg.dedup.simhash,
        kb_id=kb_id,
    )

    # minhash step (only when the simhash step found no candidates)
    if result.body_match == "none":
        from rag_api.pipeline.step.dedup.minhash import run_minhash_detection
        result = run_minhash_detection(doc_id=doc_id, text=body, title=title, cfg=cfg.dedup.minhash, kb_id=kb_id)

    # chunk_compare step (only when simhash/minhash routed a near-duplicate candidate)
    if result.body_match == "similar":
        result = run_chunk_compare(
            doc_id=doc_id, kb_id=kb_id, documents=documents, result=result, cfg=cfg.dedup.chunk_compare
        )

    run_verdict(doc_id=doc_id, result=result, run_id=run_id)
    return result
