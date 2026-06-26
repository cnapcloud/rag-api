"""Dagster @op wrappers for dedup stages — used by dedup_job (standalone / backfill)."""

from dagster import Config, OpExecutionContext, op


class DedupStageConfig(Config):
    doc_id: str


@op
def simhash_op(context: OpExecutionContext, config: DedupStageConfig):
    """Stage 1 detection: download document from MinIO, compute SHA-256 title + SimHash body."""
    from config.settings import get_settings
    from exceptions import IngestValidationError
    from infra.postgres import get_doc_by_id
    from infra.redis import get_redis_client
    from pipeline.ops.dedup.simhash import run_simhash_detection
    from pipeline.ops.dedup.types import DedupResult
    from pipeline.ops.parse import parse

    cfg = get_settings()
    if not cfg.dedup.enabled:
        context.log.info("Dedup disabled: doc_id=%s", config.doc_id)
        return DedupResult(verdict="proceed", needs_indexing=True)

    doc = get_doc_by_id(config.doc_id)
    if doc is None:
        raise IngestValidationError(f"Document not found: doc_id={config.doc_id}")

    documents = parse(doc_id=config.doc_id, storage_key=doc.get("storage_key", ""))
    title = " ".join(d.metadata.get("file_name", "") for d in documents[:1])
    body = " ".join(d.text for d in documents)

    result = run_simhash_detection(
        doc_id=config.doc_id,
        title=title,
        body=body,
        rc=get_redis_client(),
        cfg=cfg.dedup,
    )
    context.log.info(
        "SimHash detection done: verdict=%s doc_id=%s",
        result.verdict, config.doc_id,
    )
    return result


@op
def verdict_op(context: OpExecutionContext, config: DedupStageConfig, simhash_result):
    """Persist hashes and apply verdict-specific post-processing."""
    from pipeline.ops.dedup.verdict import run_verdict

    run_verdict(
        doc_id=config.doc_id,
        result=simhash_result,
        run_id=context.run_id,
    )
    context.log.info(
        "Verdict applied: verdict=%s doc_id=%s duplicate=%s",
        simhash_result.verdict, config.doc_id, simhash_result.duplicate_doc_id,
    )
