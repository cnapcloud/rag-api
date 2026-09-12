# Plan 30 — API Status Guard (US-30)

## Context

upload / delete / reindex API에서 문서가 활성 처리 중일 때 요청을 차단하는 가드가 불완전하다.
- `delete_doc`은 `running`만 차단 (나머지 활성 상태 누락)
- `reindex_doc` / `reindex_kb` / `upload_doc`은 status 체크 없음
- `enqueue_delete_event`에 `deleted` drop 가드 없음 (`enqueue_upload_event`와 비대칭)

설계 문서: `docs/internal/design/doc-status-guard.md`

## 구현 계획

### SG-01: `src/pipeline/utils/doc_state.py`

파일 하단에 추가:

```python
_STABLE_STATUSES = frozenset({"indexed", "failed", "deleted", "outdated"})

def is_active(status: str) -> bool:
    return status not in _STABLE_STATUSES
```

### SG-02: `src/api/routers/docs.py` — `delete_doc`

현재 `if status == "running":` → `is_active()` 전체로 교체:

```python
from rag_api.pipeline.utils.doc_state import is_active

status = doc.get("status", "")
if is_active(status):
    logger.warning("Delete blocked — doc active: kb=%s doc_id=%s status=%s", kb_id, doc_id, status)
    raise ConflictError(f"Document is active, try again later: doc_id={doc_id} status={status}")
```

### SG-02a: `src/pipeline/queue/enqueue.py` — `enqueue_delete_event`

`get_doc_by_id` 이후, `enqueue_upload_event`와 대칭으로 추가:

```python
if current == "deleted":
    logger.warning("enqueue_delete_event: delete event dropped for deleted doc: doc_id=%s", doc_id)
    return
```

### SG-03: `src/api/routers/docs.py` — `reindex_doc`

`enqueue_upload_event` 호출 전에 추가:

```python
from rag_api.pipeline.utils.doc_state import is_active

status = doc.get("status", "")
if is_active(status):
    logger.warning("Reindex blocked — doc active: kb=%s doc_id=%s status=%s", kb_id, doc_id, status)
    raise ConflictError(f"Document is active, try again later: doc_id={doc_id} status={status}")
```

### SG-04: `src/api/routers/docs.py` — `reindex_kb`

`pg_list_docs` 결과 순회 시 두 조건 추가:

```python
from rag_api.pipeline.utils.doc_state import is_active

status = doc.get("status", "")
if status == "outdated":
    logger.debug("Reindex skipped — doc outdated: doc_id=%s", doc["doc_id"])
    skipped += 1
    continue
if is_active(status):
    logger.debug("Reindex skipped — doc active: doc_id=%s status=%s", doc["doc_id"], status)
    skipped += 1
    continue
```

### SG-05: `src/api/routers/docs.py` — `upload_doc` / `upload_docs_batch`

기존 doc(`existing is not None`) 분기에서 `set_uploading` 호출 전에 추가:

```python
from rag_api.pipeline.utils.doc_state import is_active

if existing is not None:
    status = existing.get("status", "")
    if is_active(status):
        logger.warning("Upload blocked — doc active: kb=%s doc_id=%s status=%s", kb_id, existing["doc_id"], status)
        raise ConflictError(f"Document is active, try again later: doc_id={existing['doc_id']} status={status}")
```

`upload_docs_batch`는 동일 패턴, 개별 파일 루프 내 적용.

## 수정 파일 목록

| 파일 | 변경 |
|---|---|
| `src/pipeline/utils/doc_state.py` | `_STABLE_STATUSES`, `is_active()` 추가 |
| `src/pipeline/queue/enqueue.py` | `enqueue_delete_event` deleted 가드 추가 |
| `src/api/routers/docs.py` | delete / reindex / upload 엔드포인트 status 가드 추가 |

## 검증

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v
```

- 기존 테스트 통과 확인
- `delete_doc` 활성 상태 차단 케이스
- `reindex_doc` 활성 상태 차단 케이스
- `reindex_kb` outdated/active skip 카운트
- `upload_doc` 기존 doc 활성 상태 차단 케이스
