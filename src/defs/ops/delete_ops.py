"""Dagster @op — 문서 삭제 파이프라인."""

from dagster import Config, HookContext, OpExecutionContext, failure_hook, op


@failure_hook
def delete_failure_hook(context: HookContext) -> None:
    """Mark document as delete_failed in Postgres when any delete op fails."""
    try:
        op_config = context.op_config or {}
        kb_id: str = op_config.get("kb_id", "")
        doc_source: str = op_config.get("doc_source", "")
        if not kb_id or not doc_source:
            return
        from pipeline.ops.meta import set_failed
        set_failed(kb_id, doc_source, f"delete_job op failed: {context.op_def.name}", run_id=context.run_id)
    except Exception as e:
        context.log.error("delete_failure_hook error: %s", e)


class DeleteConfig(Config):
    kb_id: str
    doc_source: str


@op
def delete_chunks_op(context: OpExecutionContext, config: DeleteConfig):
    """Qdrant에서 doc_key 필터로 청크 전체 삭제."""
    from infra import qdrant as qdrant_infra

    qdrant_infra.delete_chunks_by_doc(config.kb_id, config.doc_source)
    context.log.info("Qdrant chunks deleted: %s/%s", config.kb_id, config.doc_source)
    return {"kb_id": config.kb_id, "doc_source": config.doc_source}


@op
def delete_meta_op(context: OpExecutionContext, delete_result: dict):
    """Postgres documents 테이블에서 문서 메타데이터 삭제."""
    from infra import postgres as postgres_infra

    postgres_infra.delete_doc_meta(delete_result["kb_id"], delete_result["doc_source"])
    context.log.info("Postgres meta deleted: %s/%s", delete_result["kb_id"], delete_result["doc_source"])