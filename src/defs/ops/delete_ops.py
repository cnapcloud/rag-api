"""Dagster @op — document delete pipeline."""

from dagster import Config, HookContext, OpExecutionContext, failure_hook, op


@failure_hook
def delete_failure_hook(context: HookContext) -> None:
    """Mark document as failed in Postgres when any delete op fails."""
    try:
        dagster_run = context.instance.get_run_by_id(context.run_id)
        run_tags = dagster_run.tags if dagster_run else {}
        doc_id: str = run_tags.get("doc_id", "")
        if not doc_id:
            return
        from pipeline.ops.meta import set_failed
        set_failed(doc_id, f"delete_job op failed: {context.op_def.name}", run_id=context.run_id)
    except Exception as e:
        context.log.error("delete_failure_hook error: %s", e)


class DeleteConfig(Config):
    doc_id: str


@op
def delete_chunks_op(context: OpExecutionContext, config: DeleteConfig):
    """Delete all Qdrant chunks for a document."""
    from infra import qdrant as qdrant_infra
    from infra.postgres import get_doc_by_id

    doc = get_doc_by_id(config.doc_id)
    if doc is None:
        context.log.warning("delete_chunks_op: doc not found: doc_id=%s", config.doc_id)
        return {"doc_id": config.doc_id, "kb_id": ""}

    kb_id = doc["kb_id"]
    qdrant_infra.delete_chunks_by_doc_id(kb_id, config.doc_id)
    context.log.info("Qdrant chunks deleted: doc_id=%s kb=%s", config.doc_id, kb_id)
    return {"doc_id": config.doc_id, "kb_id": kb_id}


@op
def delete_meta_op(context: OpExecutionContext, delete_result: dict):
    """Soft-delete the document row in Postgres."""
    from infra.postgres import soft_delete_doc

    doc_id = delete_result["doc_id"]
    soft_delete_doc(doc_id)
    context.log.info("Postgres meta soft-deleted: doc_id=%s", doc_id)
