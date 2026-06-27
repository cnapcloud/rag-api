"""Dagster @op wrapper for document delete pipeline."""

from dagster import Config, HookContext, OpExecutionContext, failure_hook, op


@failure_hook
def delete_failure_hook(context: HookContext) -> None:
    """Mark document as failed in Postgres when the delete op fails."""
    try:
        dagster_run = context.instance.get_run_by_id(context.run_id)
        run_tags = dagster_run.tags if dagster_run else {}
        doc_id: str = run_tags.get("doc_id", "")
        if not doc_id:
            return
        from pipeline.ops.meta import set_failed
        set_failed(doc_id, f"delete_job op failed: {context.op_def.name}", run_id=context.run_id)
        context.log.info("delete_failure_hook: set_failed doc_id=%s op=%s", doc_id, context.op_def.name)
    except Exception as e:
        context.log.error("delete_failure_hook error: %s", e)


class DeleteConfig(Config):
    doc_id: str


@op
def delete_op(context: OpExecutionContext, config: DeleteConfig):
    """Delete a document. Soft delete for indexed, hard delete for all other statuses."""
    from pipeline.ops.delete import delete_doc

    delete_doc(config.doc_id, run_id=context.run_id)
    context.log.info("Delete done: doc_id=%s", config.doc_id)
