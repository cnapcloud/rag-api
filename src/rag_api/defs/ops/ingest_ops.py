"""Dagster @op wrappers — wrap pipeline/ops pure functions as Dagster Ops."""

from dagster import Config, HookContext, OpExecutionContext, Out, Output, failure_hook, op


@failure_hook
def ingest_failure_hook(context: HookContext) -> None:
    """Mark document as failed in Postgres when any ingest op fails."""
    try:
        dagster_run = context.instance.get_run_by_id(context.run_id)
        run_tags = dagster_run.tags if dagster_run else {}
        doc_id: str = run_tags.get("doc_id", "")
        if not doc_id:
            context.log.info("ingest_failure_hook: doc_id not found in run tags, skip set_failed")
            return
        from rag_api.pipeline.ops.meta import set_failed
        set_failed(doc_id, f"ingest_job op failed: {context.step_key}", run_id=context.run_id)
        context.log.info("ingest_failure_hook: set_failed doc_id=%s op=%s", doc_id, context.step_key)
    except Exception as e:
        context.log.error("ingest_failure_hook error: %s", e)


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

class IngestConfig(Config):
    doc_id: str
    force: bool = False


# ──────────────────────────────────────────────
# Ops
# ──────────────────────────────────────────────

@op(out={"valid_config": Out(dagster_type=dict, is_required=False)})
def validate_op(context: OpExecutionContext, config: IngestConfig):
    """File size validation. Emits valid_config dict on success."""
    from rag_api.infra.postgres import get_doc_by_id
    from rag_api.pipeline.ops.meta import set_failed, set_processing
    from rag_api.pipeline.ops.validate import validate

    doc = get_doc_by_id(config.doc_id)
    if doc and doc.get("status") == "failed":
        context.log.warning("Job aborted: doc was force-failed before validate_op started: doc_id=%s", config.doc_id)
        return

    set_processing(config.doc_id, run_id=context.run_id)

    try:
        validate(doc_id=config.doc_id, force=config.force)
    except Exception as e:
        set_failed(config.doc_id, str(e), run_id=context.run_id)
        raise

    context.log.info("Validation passed: doc_id=%s", config.doc_id)

    from rag_api.infra.postgres import get_doc_by_id
    doc = get_doc_by_id(config.doc_id)
    kb_id = doc["kb_id"] if doc else ""
    storage_key = doc.get("storage_key", "") if doc else ""
    title = doc.get("title", "") if doc else ""
    source_type = doc.get("source_type", "") if doc else ""
    source = doc.get("source", "") if doc else ""

    yield Output(
        {
            "doc_id": config.doc_id,
            "kb_id": kb_id,
            "storage_key": storage_key,
            "title": title,
            "source_type": source_type,
            "source": source,
            "force": config.force,
            "run_id": context.run_id,
        },
        output_name="valid_config",
    )


@op
def parse_op(context: OpExecutionContext, valid_config: dict):
    """Download file from S3, convert to LlamaIndex Documents, persist doc_created_at."""
    from rag_api.infra.postgres import update_doc_fields
    from rag_api.pipeline.ops.parse import parse

    doc_id = valid_config["doc_id"]
    documents = parse(doc_id=doc_id, storage_key=valid_config["storage_key"])

    if documents:
        doc_created_at = documents[0].metadata.get("doc_created_at", "")
        if doc_created_at:
            update_doc_fields(doc_id, {"doc_created_at": doc_created_at})

    context.log.info("Parse done: %d documents doc_id=%s", len(documents), doc_id)
    return documents


@op(out={"to_chunk": Out(dagster_type=list, is_required=False)})
def dedup_op(context: OpExecutionContext, valid_config: dict, documents):
    """Run dedup pipeline (stage 1 SimHash + stage 2 MinHash/pg_trgm + stage 3 chunk_compare) on
    pre-parsed documents.

    Emits to_chunk only when needs_indexing=True; otherwise terminates the pipeline branch.
    """
    from rag_api.pipeline.ops.dedup import run_dedup_pipeline

    doc_id = valid_config["doc_id"]
    kb_id = valid_config["kb_id"]
    result = run_dedup_pipeline(doc_id=doc_id, kb_id=kb_id, run_id=context.run_id, documents=documents)

    context.log.info(
        "Dedup done: body_match=%s doc_id=%s needs_indexing=%s",
        result.body_match, doc_id, result.needs_indexing,
    )

    if not result.needs_indexing:
        return

    yield Output(documents, "to_chunk")


@op
def chunk_op(context: OpExecutionContext, to_chunk):
    """Document -> Node chunking."""
    from rag_api.exceptions import IngestValidationError
    from rag_api.pipeline.ops.chunk import chunk

    nodes = chunk(to_chunk)
    if not nodes:
        raise IngestValidationError("No indexable content: all chunks below min_chunk_chars threshold")
    context.log.info("Chunking done: %d nodes", len(nodes))
    return nodes


@op
def embed_op(context: OpExecutionContext, nodes):
    """Node -> Dense + Sparse vector embedding (asyncio parallel)."""
    from rag_api.pipeline.ops.embed import embed

    embedded = embed(nodes)
    context.log.info("Embedding done: %d nodes", len(embedded))
    return embedded


@op
def upsert_op(context: OpExecutionContext, valid_config: dict, embedded_nodes):
    """Delete existing Qdrant chunks then insert new ones."""
    from rag_api.pipeline.utils.upsert import upsert

    result = upsert(
        kb_id=valid_config["kb_id"],
        doc_id=valid_config["doc_id"],
        embedded_nodes=embedded_nodes,
        title=valid_config.get("title", ""),
        source_type=valid_config.get("source_type", ""),
        source=valid_config.get("source", ""),
    )
    context.log.info("Upsert done: %d chunks", result.chunk_count)
    return result


@op
def meta_op(context: OpExecutionContext, valid_config: dict, upsert_result):
    """Update Postgres document metadata to status=indexed."""
    from rag_api.config.settings import get_settings
    from rag_api.pipeline.ops.meta import update_meta

    storage_key = valid_config.get("storage_key", "")
    doc_type = storage_key.rsplit(".", 1)[-1] if "." in storage_key else ""

    cfg = get_settings().embedding
    update_meta(
        doc_id=valid_config["doc_id"],
        upsert_result=upsert_result,
        run_id=valid_config.get("run_id", context.run_id),
        doc_type=doc_type,
        embedding_model=cfg.model,
    )
    context.log.info(
        "ingest_job completed: doc_id=%s chunks=%d",
        valid_config["doc_id"],
        upsert_result.chunk_count,
    )
