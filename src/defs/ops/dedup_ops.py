"""Dagster @op wrappers for dedup stages — used by dedup_job (standalone / backfill)."""

from dagster import OpExecutionContext, Out, Output, op

from defs.ops.ingest_ops import IngestConfig


@op(out={"valid_config": Out(dagster_type=dict), "documents": Out(dagster_type=list)})
def parse_op(context: OpExecutionContext, config: IngestConfig):
    """Fetch doc metadata from Postgres and parse document from MinIO."""
    from exceptions import IngestValidationError
    from infra.postgres import get_doc_by_id
    from pipeline.ops.parse import parse

    doc = get_doc_by_id(config.doc_id)
    if doc is None:
        raise IngestValidationError(f"Document not found: doc_id={config.doc_id}")

    storage_key = doc.get("storage_key", "")
    documents = parse(doc_id=config.doc_id, storage_key=storage_key)
    context.log.info("Parse done: %d documents doc_id=%s", len(documents), config.doc_id)

    yield Output({"doc_id": config.doc_id, "storage_key": storage_key}, "valid_config")
    yield Output(documents, "documents")


@op
def simhash_op(context: OpExecutionContext, valid_config: dict, documents):
    """Stage 1 detection: compute SHA-256 title + SimHash body from pre-parsed documents."""
    from config.settings import get_settings
    from pipeline.ops.dedup.simhash import run_simhash_detection
    from pipeline.ops.dedup.types import DedupResult

    doc_id = valid_config["doc_id"]
    cfg = get_settings()
    if not cfg.dedup.enabled:
        context.log.info("Dedup disabled: doc_id=%s", doc_id)
        return DedupResult(verdict="proceed", needs_indexing=True)

    title = " ".join(d.metadata.get("file_name", "") for d in documents[:1])
    body = " ".join(d.text for d in documents)

    result = run_simhash_detection(
        doc_id=doc_id,
        title=title,
        body=body,
        cfg=cfg.dedup,
    )

    context.log.info(
        "SimHash detection done: body=%s title=%s doc_id=%s",
        result.body_match, result.title_match, doc_id,
    )
    return result


@op
def minhash_op(context: OpExecutionContext, valid_config: dict, documents, simhash_result):
    """Stage 2 detection: MinHash Jaccard + pg_trgm title similarity.

    Runs only when stage 1 returned 'proceed'. Otherwise passes stage 1 result through.
    """
    from config.settings import get_settings
    from pipeline.ops.dedup.minhash import run_minhash_detection
    from pipeline.ops.dedup.types import DedupResult

    doc_id = valid_config["doc_id"]

    if simhash_result.body_match != "none":
        context.log.info(
            "Stage2 skipped (body_match=%s): doc_id=%s", simhash_result.body_match, doc_id
        )
        return simhash_result

    cfg = get_settings()
    if not cfg.dedup.enabled:
        context.log.info("Dedup disabled: doc_id=%s", doc_id)
        return DedupResult(verdict="proceed", needs_indexing=True)

    title = " ".join(d.metadata.get("file_name", "") for d in documents[:1])
    body = " ".join(d.text for d in documents)

    result = run_minhash_detection(doc_id=doc_id, text=body, title=title, cfg=cfg.dedup)
    context.log.info(
        "Stage2 detection done: body=%s doc_id=%s", result.body_match, doc_id
    )
    return result


@op
def verdict_op(context: OpExecutionContext, valid_config: dict, stage2_result):
    """Apply verdict-specific post-processing for the final result from stage 1 or 2."""
    from pipeline.ops.dedup.verdict import run_verdict

    doc_id = valid_config["doc_id"]
    run_verdict(
        doc_id=doc_id,
        result=stage2_result,
        run_id=context.run_id,
    )
    context.log.info(
        "Verdict applied: body=%s title=%s doc_id=%s duplicate=%s",
        stage2_result.body_match, stage2_result.title_match,
        doc_id, stage2_result.duplicate_doc_id,
    )
    return stage2_result
