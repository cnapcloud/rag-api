# US-16 — Connector CRUD + Sync API (R-06 + R-07)

**Status**: todo
**Depends on**: US-15 (R-01 — documents/connectors 스키마 완료)
**Requirements**: R-06, R-07 in `docs/dev/requirement-multi-source-ingest.md`

---

## Goal

커넥터(Connector) 리소스에 대한 전체 CRUD 및 동기화 트리거 API를 구현한다.
실제 크롤러/커넥터 구현(WebConnector, ConfluenceConnector, GitHubConnector — R-09~R-11)은 별도 항목이며,
이 항목은 API 레이어와 BackgroundTask 디스패치 프레임워크까지만 완성한다.

---

## Endpoints

### CRUD (R-06)

| Method | Path | Description |
|---|---|---|
| POST | `/api/connectors` | 커넥터 생성 |
| GET | `/api/connectors` | 목록 조회 (kb_id, source_type, status 필터) |
| GET | `/api/connectors/{connector_id}` | 단건 조회 |
| PATCH | `/api/connectors/{connector_id}` | config / schedule / status 변경 |
| DELETE | `/api/connectors/{connector_id}` | 커넥터 삭제 + 연결 문서 cascade soft-delete (202 async) |

### Sync (R-07)

| Method | Path | Description |
|---|---|---|
| POST | `/api/connectors/{connector_id}/sync` | 수동 동기화 트리거 (202 async) |
| GET | `/api/connectors/{connector_id}/sync/status` | 현재 sync 상태 + doc_counts |
| GET | `/api/connectors/{connector_id}/docs` | 이 커넥터가 인제스트한 문서 목록 |

---

## Key Behaviors

### DELETE cascade (BackgroundTask, 202)

```
[1] Set connector.status = deleting
[2] For each document WHERE connector_id = ? AND status != deleted:
      [a] Delete Qdrant chunks by doc_id
      [b] Delete object storage file by storage_key (silent-fail: log warning on S3Error)
      [c] Set document status = deleted, deleted_at = NOW()
[3] DELETE connector row from Postgres
```

Documents re-uploaded via API (connector_id = NULL) are excluded — not owned by this connector.

### POST /sync concurrency guard

```
sync_status = running AND sync_started_at > NOW() - 30min  -> 409 "sync already in progress"
sync_status = running AND sync_started_at <= NOW() - 30min -> stale lock, proceed (reset)
connector.status = paused                                   -> 409 "connector is paused"
```

Returns 202 immediately; dispatches to connector implementation as BackgroundTask.

Connector implementation for each source_type (web/confluence/github) does not exist yet at this stage.
The dispatch function raises `ConfigError("connector type not yet implemented: {source_type}")` as a placeholder.
This allows the API layer to be tested without actual crawlers.

### GET /sync/status — doc_counts

```json
{
  "connector_id": "...",
  "status": "active",
  "sync_status": "idle",
  "sync_started_at": null,
  "last_synced_at": "2025-01-01T02:00:00Z",
  "doc_counts": {
    "indexed": 142,
    "pending": 3,
    "failed": 1,
    "deleted": 5,
    "total": 151
  }
}
```

`total` includes all statuses (including deleted).

### PATCH allowed fields

`name`, `config`, `sync_schedule`, `schedule_enabled`, `status` (active/paused only — error is set by system).
`source_type` and `kb_id` are immutable after creation.

---

## Acceptance Criteria

- [ ] POST /api/connectors creates a row; duplicate connector_id returns 409
- [ ] GET /api/connectors returns filtered list; `status=deleted` rows excluded by default
- [ ] PATCH cannot change source_type or kb_id
- [ ] DELETE returns 202; documents status → deleted; connector row removed
- [ ] POST /sync returns 409 when already running (within 30min window)
- [ ] POST /sync returns 409 when connector is paused
- [ ] POST /sync returns 202 and sets sync_status=running; background dispatch raises ConfigError (placeholder)
- [ ] GET /sync/status returns correct doc_counts by status
- [ ] GET /docs returns documents filtered by connector_id (excludes status=deleted by default)
- [ ] All endpoints return 404 via NotFoundError when connector_id not found
- [ ] All tests use conftest.py fixtures (no real DB connections)
