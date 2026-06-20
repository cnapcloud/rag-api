"""Dagster @op 래퍼 — pipeline/ops 순수 함수를 Dagster Op으로 감싼다."""

from dagster import Config, HookContext, OpExecutionContext, Out, Output, failure_hook, op


@failure_hook
def ingest_failure_hook(context: HookContext) -> None:
    """Mark document as failed in Redis when any ingest op fails."""
    try:
        op_config = context.op_config or {}
        kb_id: str = op_config.get("kb_id", "")
        doc_source: str = op_config.get("doc_source", "")
        if not kb_id or not doc_source:
            return
        from pipeline.ops.meta import set_failed
        set_failed(kb_id, doc_source, f"ingest_job op failed: {context.op_def.name}", run_id=context.run_id)
    except Exception as e:
        context.log.error("ingest_failure_hook error: %s", e)


# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────

class IngestConfig(Config):
    kb_id: str
    doc_source: str
    etag: str
    file_size: int = 0
    force: bool = False


# ──────────────────────────────────────────────
# Ops
# ──────────────────────────────────────────────

@op(out={"valid_config": Out(dagster_type=dict, is_required=False)})
def validate_op(context: OpExecutionContext, config: IngestConfig):
    """ETag 중복·크기 검증. 중복이면 Output 미발행 → 이후 Op 자동 스킵."""
    from pipeline.ops.meta import set_failed, set_processing
    from pipeline.ops.validate import validate

    set_processing(config.kb_id, config.doc_source, run_id=context.run_id)

    try:
        should_process = validate(
            kb_id=config.kb_id,
            doc_source=config.doc_source,
            etag=config.etag,
            file_size=config.file_size,
            force=config.force,
        )
    except Exception as e:
        set_failed(config.kb_id, config.doc_source, str(e), run_id=context.run_id)
        raise

    if should_process:
        context.log.info("Validation passed: %s/%s", config.kb_id, config.doc_source)
        yield Output(
            {
                "kb_id": config.kb_id,
                "doc_source": config.doc_source,
                "etag": config.etag,
                "file_size": config.file_size,
                "run_id": context.run_id,
            },
            output_name="valid_config",
        )
    else:
        from pipeline.ops.meta import restore_indexed
        restore_indexed(config.kb_id, config.doc_source, etag=config.etag)
        context.log.info("ETag unchanged, skipping: %s/%s", config.kb_id, config.doc_source)


@op
def parse_op(context: OpExecutionContext, valid_config: dict):
    """S3에서 파일 다운로드 후 LlamaIndex Document 변환."""
    from pipeline.ops.parse import parse

    documents = parse(kb_id=valid_config["kb_id"], doc_source=valid_config["doc_source"])
    context.log.info("Parse done: %d documents", len(documents))
    return documents


@op
def chunk_op(context: OpExecutionContext, documents):
    """Document → Node 청킹."""
    from pipeline.ops.chunk import chunk

    nodes = chunk(documents)
    context.log.info("Chunking done: %d nodes", len(nodes))
    return nodes


@op
def embed_op(context: OpExecutionContext, nodes):
    """Node → Dense + Sparse 벡터 임베딩 (asyncio 병렬)."""
    from pipeline.ops.embed import embed

    embedded = embed(nodes)
    context.log.info("Embedding done: %d nodes", len(embedded))
    return embedded


@op
def upsert_op(context: OpExecutionContext, valid_config: dict, embedded_nodes):
    """Qdrant 기존 청크 삭제 → 신규 삽입."""
    from pipeline.ops.upsert import upsert

    result = upsert(
        kb_id=valid_config["kb_id"],
        doc_source=valid_config["doc_source"],
        embedded_nodes=embedded_nodes,
    )
    context.log.info("Upsert done: %d chunks", result.chunk_count)
    return result


@op
def meta_op(context: OpExecutionContext, valid_config: dict, upsert_result):
    """Redis 메타데이터 갱신 (status=indexed)."""
    from config.settings import get_settings
    from pipeline.ops.meta import update_meta

    cfg = get_settings().embedding
    update_meta(
        kb_id=valid_config["kb_id"],
        doc_source=valid_config["doc_source"],
        upsert_result=upsert_result,
        etag=valid_config.get("etag", ""),
        run_id=valid_config.get("run_id", context.run_id),
        file_size=valid_config.get("file_size", 0),
        doc_type=valid_config["doc_source"].rsplit(".", 1)[-1],
        embedding_model=cfg.model,
        doc_created_at=upsert_result.doc_created_at,
    )
    context.log.info(
        "ingest_job completed: kb=%s key=%s chunks=%d",
        valid_config["kb_id"],
        valid_config["doc_source"],
        upsert_result.chunk_count,
    )