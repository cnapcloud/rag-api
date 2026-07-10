# 커넥터 상태 흐름과 API 관계

## 1. 개요

커넥터는 두 개의 독립적인 상태 필드와 마지막 에러 메시지를 가진다.

| 필드 | 타입 | 의미 |
|------|------|------|
| `status` | 커넥터 자체 운영 상태 | 활성화/일시중단/오류/삭제 중 |
| `sync_status` | 현재 sync 실행 여부 | 실행 중 / 유휴 |
| `last_error` | 마지막 sync 실패 메시지 (500자 제한) | `status=error`가 아니어도 과거 기록이 남아있을 수 없음 — `status`가 `error`가 아닌 값으로 바뀌는 순간 항상 함께 클리어됨 |

두 상태 필드는 독립적으로 관리된다. `status=error`이어도 `sync_status=idle`이면 수동 sync는 가능하다.

---

## 2. status 상태

| 값 | 진입 조건 | 설명 |
|----|-----------|------|
| `active` | 생성 시 기본값, `paused`에서 resume, 또는 (이전 상태가 `error`였더라도) sync 성공 시 자동 복구 | 정상 운영. 수동/자동 sync 모두 허용 |
| `paused` | `PATCH /connectors/{id}` — `status: paused` | 전면 중단. 수동/자동 sync 모두 차단 |
| `error` | sync 실패 시 자동 설정 | 마지막 sync가 예외로 종료됨. sync 재시도는 가능. 예외 메시지가 `last_error`에 기록됨 (`GET /connectors/{id}/sync/status`, `GET /connectors/{id}`로 로그 없이 확인 가능) |
| `deleting` | `DELETE /connectors/{id}` | 캐스케이드 삭제 진행 중. 완료 후 레코드 삭제 |

### status 전이

```
           PATCH(pause)
  active ──────────────► paused
    ▲                       │
    │     PATCH(resume)     │
    └───────────────────────┘

  active/paused/error ──(sync 실패: 예외 발생)──► error (last_error = 예외 메시지)
  error               ──(sync 재시도 성공, abort 아님)──► active (last_error = NULL로 자동 클리어)
  error/active/paused ──(PATCH status: active|paused)──► 지정 상태 (last_error = NULL로 클리어)

  any ──(DELETE 호출)──► deleting ──(cascade 완료)──► (레코드 삭제)
```

> `error` → `active` 자동 복구는 sync가 예외 없이 완료됐을 때만 일어난다 (`_run_sync`/`connector_sync_op`가 `_dispatch_sync` 완료 후 `set_connector_status(connector_id, "active")` 호출). abort로 중단된 sync는 "정상 완료"가 아니므로 status를 건드리지 않고 이전 상태(예: `error`)를 그대로 둔다 — abort 자체가 실패 원인을 고친 것은 아니기 때문이다.

---

## 3. sync_status 상태

| 값 | 진입 조건 | 설명 |
|----|-----------|------|
| `idle` | 초기값, sync 완료, abort, 실패 | sync 실행 없음 |
| `running` | sync 트리거 직후 | 백그라운드 스레드(또는 Dagster op)가 실행 중 |

### sync_status 전이

```
         POST /sync (또는 Dagster Schedule)
  idle ────────────────────────────────────► running
                                                │
                    ┌───────────────────────────┤──────────────────────┐
                    │                           │                      │
               정상 완료                   sync 실패               abort 호출
                    │                           │                      │
                    │                  status → error          (즉시 전환,
                    │                           │               스레드 대기 없음)
                    └───────────────────────────┴──────────────────────┘
                                                ▼
                                              idle
```

---

## 4. API별 허용 조건

### POST /connectors/{id}/sync — 수동 sync 트리거

| 조건 | 결과 |
|------|------|
| `status == "paused"` | 409 — Connector is paused |
| `sync_status == "running"` | 409 — Sync already in progress |
| 그 외 | 202 — sync 시작, `sync_status → running` |

### POST /connectors/{id}/sync/abort — sync 중단

| 조건 | 결과 |
|------|------|
| `sync_status != "running"` | 409 — No sync in progress |
| `sync_status == "running"` | 202 — 중단 처리 시작 |

abort 호출 시 수행되는 작업 (순서대로):

1. `sync_status → idle` (즉시)
2. 이 커넥터 소속 `pending` 문서를 Redis 큐에서 제거 + `status → failed`
3. 이 커넥터 소속 `running` 문서를 `status → failed` + Dagster run force-terminate
4. 커넥터 sync 루프에 abort 신호 전달 — 다음 페이지 요청 전에 루프 종료

### PATCH /connectors/{id} — pause / resume

| 필드 | 설명 |
|------|------|
| `status: "paused"` | sync 차단. 진행 중인 sync는 중단하지 않음 |
| `status: "active"` | sync 재허용 |

pause는 sync를 강제 종료하지 않는다. 진행 중인 sync를 즉시 멈추려면 abort를 먼저 호출해야 한다.

### DELETE /connectors/{id} — 커넥터 삭제

`status → deleting` 후 백그라운드에서 cascade 삭제를 수행한다.

- 소속 문서의 Qdrant 청크 삭제
- S3 파일 삭제
- Postgres 문서 레코드 삭제
- 커넥터 레코드 삭제

진행 중인 sync는 cascade 삭제와 병렬로 실행될 수 있다. 삭제 전 abort를 먼저 호출하는 것을 권장한다.

---

## 5. 자동 sync (Dagster Schedule)

`sync_schedule`이 설정된 커넥터는 `connector_sync_job`이 Dagster Schedule로 자동 실행된다.

자동 sync의 허용 조건:

| 조건 | 동작 |
|------|------|
| `status == "paused"` | skip (로그만 남김) |
| `sync_status == "running"` (1시간 미만) | skip |
| `sync_status == "running"` (1시간 초과) | stale lock으로 판단하고 진행 |

수동 트리거와 달리 자동 sync는 stale lock 예외가 있다. 1시간 이상 stuck된 경우 스케줄러가 재트리거를 허용한다.

---

## 6. sync 실패 시 상태

sync 실패란 `_dispatch_sync()`(커넥터 크롤/페치 루프)가 처리되지 않은 예외를 던지는 경우다. 개별 문서 인덱싱 실패(`doc.status → failed`)는 sync 실패가 아니며 커넥터 상태에 영향을 주지 않는다.

### 수동/자동 sync 실패 (abort 없이 예외 발생)

```
connector.status      → "error"
connector.sync_status → "idle"
```

### abort 진행 중 예외 발생

```
connector.status      → 변경 없음 (error로 기록하지 않음)
connector.sync_status → "idle" (abort 호출 시점에 이미 전환됨)
```

abort 중 백그라운드 스레드에서 예외가 발생하면 로그만 남긴다. abort는 사용자의 의도적인 중단이므로 sync 실패와 구분한다.

---

## 7. 서버 재시작 시 sync_status 복구

서버(FastAPI)가 재시작되면 백그라운드 스레드가 종료되지만 `sync_status`는 Postgres에 `"running"`으로 남는다.

이 상태에서:

- 수동 sync 트리거 → 409 차단
- 자동 Dagster Schedule → 1시간 후 stale lock으로 재트리거

**수동 복구**: `POST /sync/abort`를 호출하면 즉시 `sync_status → idle`로 전환된다. 이 시점에는 실제 실행 중인 프로세스가 없으므로 큐/Dagster 작업은 없고 상태 전환만 발생한다.

---

## 8. 구현 위치

| 구성 요소 | 위치 |
|-----------|------|
| sync 트리거 / abort / reset | `src/api/routers/connectors.py` |
| sync 실행 루프 (`_run_sync`) | `src/api/routers/connectors.py` |
| abort 플래그 레지스트리 | `src/connectors/abort.py` |
| Dagster 자동 sync op | `src/defs/ops/connector_sync_op.py` |
| Dagster run force-terminate | `src/infra/dagster_utils.py` |
| connector status/sync_status 업데이트 | `src/infra/postgres.py` — `set_connector_status`, `set_connector_sync_status` |
| 큐 제거 | `src/pipeline/queue/enqueue.py` — `dequeue_upload_events` |
