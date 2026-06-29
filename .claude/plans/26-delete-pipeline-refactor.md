---
plan: 26
title: Delete Pipeline Refactor — soft/hard delete 분기 + status guard
covers: US-26
status: todo
---

## 구현 순서

### Step 1 — `infra/postgres.py`: `hard_delete_doc` 추가

```python
def hard_delete_doc(doc_id: str) -> None:
    """Physically delete the document row. Cascades to simhash_bands and minhash_bands."""
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM documents WHERE doc_id = %s", [doc_id])
        conn.commit()
    logger.info("Doc hard-deleted: doc_id=%s", doc_id)
```

---

### Step 2 — `pipeline/ops/delete.py` 신규 생성 (순수 함수)

```python
def delete_doc(doc_id: str, run_id: str = "direct") -> None:
    """Delete a document. Branches on status:
    - indexed  → soft delete: Qdrant chunks removed, S3 kept, DB status='deleted'
    - all else → hard delete: Qdrant chunks attempted, S3 deleted, DB row removed
    """
```

분기 로직:
```
1. get_doc_by_id → None이면 warning + return
2. status == "deleting" → info + return  (2차 방어, deleted는 통과해서 hard delete)
3. set_deleting(doc_id, run_id)      → UI에 deleting 표시
4. status == "indexed"
     → delete_chunks_by_doc_id
     → soft_delete_doc
5. else
     → delete_chunks_by_doc_id  (실패 무시)
     → delete_by_key(storage_key) (실패 무시, S3 없으면 skip)
     → hard_delete_doc           → CASCADE: simhash_bands, minhash_bands 자동 정리
```

---

### Step 3 — `api/routers/docs.py`: status guard 추가 (1차 차단)

`DELETE /kb/{kb_id}/docs/{doc_id}` 엔드포인트에서 enqueue 전 체크:

| status | 응답 |
|--------|------|
| `running` | 409 ConflictError "Document is currently being processed, try again later" |
| `deleting` | 409 ConflictError "Document is already being deleted" |
| `deleted` | 202 + enqueue (hard delete 경로 진행) |
| 그 외 | 202 + enqueue_delete_event |

---

### Step 4 — `defs/ops/delete_ops.py`: 3개 op → 1개 op

기존 `delete_chunks_op`, `delete_s3_op`, `delete_meta_op` 제거.
신규 `delete_op` 1개:

```python
@op
def delete_op(context: OpExecutionContext, config: DeleteConfig):
    from rag_api.pipeline.ops import delete_doc
    delete_doc(config.doc_id, run_id=context.run_id)
    context.log.info("Delete done: doc_id=%s", config.doc_id)
```

`delete_failure_hook`은 그대로 유지.

---

### Step 5 — `defs/jobs/delete_job.py`: 단순화

```python
@job(...)
def delete_job():
    delete_op()
```

---

### Step 6 — `pipeline/ops/runner.py`: `run_delete_pipeline` 교체

기존 인라인 로직 제거, `delete_doc` 호출로 교체:

```python
def run_delete_pipeline(doc_id: str) -> None:
    from rag_api.pipeline.ops import delete_doc
    from rag_api.pipeline.ops.meta import set_failed

    try:
        delete_doc(doc_id, run_id="direct")
        logger.info("Delete done: doc_id=%s", doc_id)
    except Exception as e:
        set_failed(doc_id, f"delete_pipeline failed: {e}")
        logger.exception("Delete pipeline failed: doc_id=%s", doc_id)
        raise
```

---

## 주의사항

- `set_deleting`은 `delete_doc` 내부에서 호출 (status 읽기 이후). runner.py에서 pre-call 제거.
- hard delete 경로에서 S3/Qdrant 실패는 warning 로그 후 계속 진행 (hard_delete_doc는 항상 실행).
- delay queue (running 문서 대기 로직)는 변경 없음.
- `connectors.py` `_cascade_delete`는 별도 경로 — 이번 범위 외.
