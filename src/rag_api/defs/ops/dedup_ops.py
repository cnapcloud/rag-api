"""Dagster @op wrappers for dedup stages — used by dedup_job (standalone / backfill)."""

from dagster import OpExecutionContext, Out, Output, op

from rag_api.defs.ops.ingest_ops import IngestConfig


@op(out={"valid_config": Out(dagster_type=dict), "documents": Out(dagster_type=list)})
def parse_op(context: OpExecutionContext, config: IngestConfig):
    """Fetch doc metadata from Postgres and parse document from MinIO."""
    from rag_api.exceptions import IngestValidationError
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.pipeline.steps.parse import parse

    doc = get_doc_by_id(config.doc_id)
    if doc is None:
        raise IngestValidationError(f"Document not found: doc_id={config.doc_id}")

    storage_key = doc.get("storage_key", "")
    kb_id = doc.get("kb_id", "")
    documents = parse(doc_id=config.doc_id, kb_id=kb_id or None, storage_key=storage_key)
    context.log.info("Parse done: %d documents doc_id=%s", len(documents), config.doc_id)

    yield Output({"doc_id": config.doc_id, "kb_id": kb_id, "storage_key": storage_key}, "valid_config")
    yield Output(documents, "documents")


@op
def simhash_op(context: OpExecutionContext, valid_config: dict, documents):
    """Simhash step detection: compute SHA-256 title + SimHash body from pre-parsed documents."""
    from rag_api.config.settings import resolve_settings
    from rag_api.pipeline.steps.dedup import is_document, run_simhash_detection
    from rag_api.pipeline.steps.dedup.types import DedupResult

    doc_id = valid_config["doc_id"]
    kb_id = valid_config["kb_id"]
    cfg = resolve_settings(kb_id or None)
    if not cfg.dedup.enabled:
        context.log.info("Dedup disabled: doc_id=%s", doc_id)
        return DedupResult(needs_indexing=True)

    if not is_document(documents):
        doc_type = documents[0].metadata.get("doc_type", "") if documents else ""
        context.log.info("Dedup skipped (non-document type=%s): doc_id=%s", doc_type, doc_id)
        return DedupResult(needs_indexing=True)

    title = " ".join(d.metadata.get("file_name", "") for d in documents[:1])
    body = " ".join(d.text for d in documents)

    result = run_simhash_detection(
        doc_id=doc_id,
        title=title,
        body=body,
        cfg=cfg.dedup.simhash,
        kb_id=kb_id,
    )

    context.log.info(
        "SimHash detection done: body=%s title=%s doc_id=%s",
        result.body_match, result.title_match, doc_id,
    )
    return result


@op
def minhash_op(context: OpExecutionContext, valid_config: dict, documents, simhash_result):
    """Minhash step detection: MinHash Jaccard + pg_trgm title similarity.

    Runs only when the simhash step returned 'proceed'. Otherwise passes the simhash
    step result through.
    """
    from rag_api.config.settings import resolve_settings
    from rag_api.pipeline.steps.dedup import is_document
    from rag_api.pipeline.steps.dedup.minhash import run_minhash_detection
    from rag_api.pipeline.steps.dedup.types import DedupResult

    doc_id = valid_config["doc_id"]
    kb_id = valid_config["kb_id"]

    if simhash_result.body_match != "none":
        context.log.info(
            "Minhash step skipped (body_match=%s): doc_id=%s", simhash_result.body_match, doc_id
        )
        return simhash_result

    cfg = resolve_settings(kb_id or None)
    if not cfg.dedup.enabled:
        context.log.info("Dedup disabled: doc_id=%s", doc_id)
        return DedupResult(needs_indexing=True)

    if not is_document(documents):
        doc_type = documents[0].metadata.get("doc_type", "") if documents else ""
        context.log.info("Minhash step skipped (non-document type=%s): doc_id=%s", doc_type, doc_id)
        return DedupResult(needs_indexing=True)

    title = " ".join(d.metadata.get("file_name", "") for d in documents[:1])
    body = " ".join(d.text for d in documents)

    result = run_minhash_detection(doc_id=doc_id, text=body, title=title, cfg=cfg.dedup.minhash, kb_id=kb_id)
    context.log.info(
        "Minhash step done: body=%s doc_id=%s", result.body_match, doc_id
    )
    return result


@op
def chunk_compare_op(context: OpExecutionContext, valid_config: dict, documents, minhash_result):
    """Chunk_compare step (stage 3): confirms body_match for 'similar' results from the
    simhash/minhash steps via chunk-level embedding cosine similarity.

    Runs only when minhash_result.body_match == 'similar'. Otherwise passes the result through.
    """
    from rag_api.config.settings import resolve_settings
    from rag_api.pipeline.steps.dedup.chunk_compare import run_chunk_compare

    doc_id = valid_config["doc_id"]
    kb_id = valid_config["kb_id"]

    if minhash_result.body_match != "similar":
        context.log.info(
            "chunk_compare step skipped (body_match=%s): doc_id=%s", minhash_result.body_match, doc_id
        )
        return minhash_result

    cfg = resolve_settings(kb_id or None)
    result = run_chunk_compare(
        doc_id=doc_id, kb_id=kb_id, documents=documents, result=minhash_result, cfg=cfg.dedup.chunk_compare
    )
    context.log.info(
        "chunk_compare step done: body=%s doc_id=%s duplicate=%s",
        result.body_match, doc_id, result.duplicate_doc_id,
    )
    return result


@op
def verdict_op(context: OpExecutionContext, valid_config: dict, chunk_compare_result):
    """Apply verdict-specific post-processing for the final result from the detection stages."""
    from rag_api.pipeline.steps.dedup.verdict import run_verdict

    doc_id = valid_config["doc_id"]
    run_verdict(
        doc_id=doc_id,
        result=chunk_compare_result,
        run_id=context.run_id,
    )
    context.log.info(
        "Verdict applied: body=%s title=%s doc_id=%s duplicate=%s",
        chunk_compare_result.body_match, chunk_compare_result.title_match,
        doc_id, chunk_compare_result.duplicate_doc_id,
    )
    return chunk_compare_result
