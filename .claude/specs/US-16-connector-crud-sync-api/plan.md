# Plan 16 — Connector CRUD + Sync API (R-06 + R-07)

Covers: US-16
Requirement: docs/dev/requirement-multi-source-ingest.md — R-06, R-07
Status: todo

---

## Overview

커넥터 리소스 전체를 다루는 API 레이어와 동기화 디스패치 프레임워크를 구현한다.
실제 크롤러 구현(R-09~R-11)은 이 플랜의 범위 밖이다.

구현 범위:
- `infra/postgres.py` — connectors CRUD 함수 추가
- `api/routers/connectors.py` — 신규 라우터
- `api/app.py` — 라우터 등록
- `tests/unit/test_connectors_api.py` — 단위 테스트

---

## Step 1 — infra/postgres.py: connectors CRUD

추가할 함수:

```python
create_connector(connector_id, kb_id, name, source_type, config, sync_schedule, schedule_enabled) -> dict
get_connector(connector_id) -> dict | None
list_connectors(kb_id=None, source_type=None, status=None) -> list[dict]
update_connector(connector_id, **fields) -> dict | None   # name/config/sync_schedule/schedule_enabled/status
delete_connector(connector_id) -> None
set_connector_sync_status(connector_id, sync_status, sync_started_at=None, last_synced_at=None) -> None
get_connector_doc_counts(connector_id) -> dict[str, int]   # {status: count, ..., "total": n}
set_connector_status(connector_id, status) -> None          # active/paused/error/deleting
```

반환 타입은 `dict` (Pydantic 변환은 라우터 레이어에서).

Pydantic 응답 모델은 라우터 파일에 정의한다 — `infra/` 레이어는 dict 반환만 담당.

---

## Step 2 — api/routers/connectors.py: CRUD endpoints

### Pydantic models

```python
class ConnectorCreate(BaseModel):
    connector_id: str
    kb_id: str
    name: str
    source_type: Literal["web", "confluence", "github"]
    config: dict
    sync_schedule: str | None = None
    schedule_enabled: bool = False

class ConnectorPatch(BaseModel):
    name: str | None = None
    config: dict | None = None
    sync_schedule: str | None = None
    schedule_enabled: bool | None = None
    status: Literal["active", "paused"] | None = None  # error는 시스템 전용

class ConnectorResponse(BaseModel):
    connector_id: str
    kb_id: str
    name: str
    source_type: str
    config: dict
    sync_schedule: str | None
    schedule_enabled: bool
    sync_status: str
    sync_started_at: datetime | None
    last_synced_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime
```

### POST /api/connectors

- KB 존재 여부 확인 (`get_kb()`) — 없으면 NotFoundError
- connector_id 충돌 시 ConflictError
- `create_connector()` 호출 후 201 반환

### GET /api/connectors

- `kb_id`, `source_type`, `status` 쿼리 파라미터로 필터
- `list_connectors()` 호출, 200 반환

### GET /api/connectors/{connector_id}

- `get_connector()` → None이면 NotFoundError

### PATCH /api/connectors/{connector_id}

- 없으면 NotFoundError
- `source_type`, `kb_id` 변경 시도는 422 (validate in Pydantic or router check)
- `update_connector()` 호출, 200 반환

### DELETE /api/connectors/{connector_id} — 202 async

```python
@router.delete("/{connector_id}", status_code=202)
async def delete_connector_endpoint(connector_id: str, background_tasks: BackgroundTasks):
    connector = get_connector(connector_id)
    if not connector:
        raise NotFoundError(...)
    set_connector_status(connector_id, "deleting")
    background_tasks.add_task(_cascade_delete, connector_id)
    return {"connector_id": connector_id, "status": "deleting"}
```

`_cascade_delete(connector_id)` 내부 순서:
```
1. docs = list documents WHERE connector_id = ? AND status != deleted
2. for doc in docs:
     a. delete_qdrant_chunks_by_doc_id(doc["doc_id"])
     b. try: delete_by_key(doc["storage_key"]) except S3Error: log warning
     c. set_document_status(doc["doc_id"], "deleted", deleted_at=now)
3. delete_connector(connector_id)
```

---

## Step 3 — api/routers/connectors.py: Sync endpoints

### POST /api/connectors/{connector_id}/sync — 202 async

```
[1] get_connector() — NotFoundError if missing
[2] connector.status == "paused"  -> 409
[3] sync_status == "running":
      sync_started_at > NOW() - 30min  -> 409
      else                             -> stale lock, proceed
[4] set_connector_sync_status(connector_id, "running", sync_started_at=NOW())
[5] background_tasks.add_task(_run_sync, connector)
[6] return 202
```

`_run_sync(connector)` 내부:
```python
try:
    _dispatch_sync(connector)  # raises ConfigError for unimplemented types
    set_connector_sync_status(connector_id, "idle", last_synced_at=NOW(), sync_started_at=None)
except Exception as e:
    set_connector_status(connector_id, "error")
    set_connector_sync_status(connector_id, "idle", sync_started_at=None)
    logger.error("Connector sync failed: connector_id=%s err=%s", connector_id, e)

def _dispatch_sync(connector):
    source_type = connector["source_type"]
    # Placeholder — actual implementations added in R-09/R-10/R-11
    raise ConfigError(f"connector type not yet implemented: {source_type}")
```

### GET /api/connectors/{connector_id}/sync/status

```python
class SyncStatusResponse(BaseModel):
    connector_id: str
    status: str
    sync_status: str
    sync_started_at: datetime | None
    last_synced_at: datetime | None
    doc_counts: dict[str, int]
```

`doc_counts` = `get_connector_doc_counts(connector_id)`.

### GET /api/connectors/{connector_id}/docs

- `list_documents(connector_id=connector_id, include_deleted=False)` 사용
- 기존 `GET /api/kb/{kb_id}/docs`와 동일한 페이지네이션/정렬 파라미터 지원

---

## Step 4 — app.py 라우터 등록

```python

from rag_api.api.routers import connectors

app.include_router(connectors.router, prefix="/api/connectors", tags=["connectors"])
```

---

## Step 5 — 테스트 (tests/unit/test_connectors_api.py)

모든 테스트는 `conftest.py` 픽스처 사용 (실제 DB/Qdrant/S3 연결 금지).

커버할 케이스:

| 테스트 | 검증 포인트 |
|---|---|
| `test_create_connector` | 201, response fields |
| `test_create_connector_duplicate` | 409 ConflictError |
| `test_create_connector_kb_not_found` | 404 NotFoundError |
| `test_list_connectors_filter` | kb_id / source_type / status 필터 동작 |
| `test_get_connector_not_found` | 404 |
| `test_patch_connector` | name/config/schedule 변경 |
| `test_patch_connector_immutable_fields` | source_type/kb_id 변경 시 422 |
| `test_delete_connector_202` | 202 즉시 반환 |
| `test_delete_cascade_calls` | Qdrant delete + S3 delete + doc status=deleted 호출 확인 |
| `test_sync_trigger_202` | 202 + sync_status=running |
| `test_sync_trigger_409_running` | 30분 이내 실행 중 -> 409 |
| `test_sync_trigger_stale_lock` | 30분 초과 running -> 재트리거 허용 |
| `test_sync_trigger_paused` | status=paused -> 409 |
| `test_sync_status_response` | doc_counts 필드 검증 |
| `test_connector_docs_list` | connector_id 필터 문서 목록 |

---

## Implementation Notes

- `connector_id`는 클라이언트가 지정 (UUID가 아닌 slug 허용 — `TEXT PRIMARY KEY`).
  POST body에 필수 포함; 중복 시 ConflictError.
- `config` 필드는 JSONB — Pydantic에서 `dict`로 받아 그대로 저장. source_type별 검증은 R-09 이후.
- `auth_token_secret`은 config 안의 key name만 저장; 실제 토큰 값은 절대 DB에 저장하지 않는다.
- `_cascade_delete`의 S3 delete는 silent-fail (S3Error 발생 시 warning 로그 후 계속).
- `_cascade_delete`의 Qdrant delete 실패는 propagate — 데이터 정합성 우선.
- BackgroundTask는 FastAPI 내장 `BackgroundTasks` 사용 (별도 큐 없음).
