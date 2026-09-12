---
plan: 32
title: Connector Schedule Hot Reload
covers: US-32
status: in-progress
---

## 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/infra/dagster_utils.py` | `reload_code_location()` 함수 추가 |
| `src/api/routers/connectors.py` | POST / PATCH / DELETE 엔드포인트에 reload background task 삽입 |

## 구현 상세

### 1. `infra/dagster_utils.py` — `reload_code_location()`

```python
_RELOAD_MUTATION = """
mutation {
  reloadRepositoryLocation(repositoryLocationName: "grpc:dagster-rag-api:4000") {
    __typename
    ... on WorkspaceLocationEntry { name }
    ... on ReloadNotSupported { message }
    ... on RepositoryLocationNotFound { message }
  }
}
"""

def reload_code_location() -> None:
    """Reload Dagster code location to pick up schedule changes.

    Non-fatal: logs warning on failure. Skip in queue_worker mode.
    """
```

- `cfg.dagster.endpoint` 사용 (하드코딩 금지).
- location name도 `cfg.dagster.location_name` 으로 설정에서 읽음.
  → `DagsterSettings`에 `location_name: str = "grpc:dagster-rag-api:4000"` 추가.
- 실패 시 `logger.warning` 후 반환 (raise 금지).

### 2. `connectors.py` 트리거 조건

| 엔드포인트 | 조건 | 비고 |
|------------|------|------|
| `POST /` | `body.sync_schedule is not None` | 새 스케줄 등록 |
| `PATCH /{id}` | `"sync_schedule" in fields` | cron 변경 또는 제거 |
| `DELETE /{id}` | connector의 `sync_schedule is not None` | 스케줄 해제 |

BackgroundTasks에 `reload_code_location` 추가 (cascade delete와 동일 패턴).
