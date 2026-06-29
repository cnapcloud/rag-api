---
id: US-32
title: Connector Schedule Hot Reload via Dagster Code Location Reload
status: in-progress
---

## User Story

커넥터의 `sync_schedule`(cron 식)을 API로 변경하거나 커넥터를 추가/삭제할 때,
Dagster를 재시작하지 않고도 스케줄이 즉시 반영되어야 한다.

## Background

`ScheduleDefinition`의 cron 식은 Dagster 시작 시 정적으로 등록된다.
변경을 반영하려면 `reloadRepositoryLocation` GraphQL mutation으로
code location(gRPC user code subprocess)을 재로드해야 한다.

`schedule_enabled` / `status` 변경은 `execution_fn` 내에서 실행 시점에
Postgres를 읽으므로 reload 없이 즉시 반영된다.

## Acceptance Criteria

- `PATCH /api/connectors/{id}` 에서 `sync_schedule` 필드가 포함된 경우, Postgres 업데이트 후 Dagster code location reload를 트리거한다.
- `POST /api/connectors` 에서 `sync_schedule`이 non-null인 경우 reload를 트리거한다.
- `DELETE /api/connectors/{id}` 에서 삭제된 커넥터가 `sync_schedule`을 가지고 있었다면 reload를 트리거한다.
- reload 실패는 경고 로그만 남기고 API 응답에 영향을 주지 않는다 (non-fatal).
- `queue_worker.enabled = true` 모드에서는 Dagster가 없으므로 reload를 skip한다.

## Implementation Notes

- `infra/dagster_utils.py`에 `reload_code_location()` 함수 추가 (기존 `terminate_dagster_run` 패턴 재사용).
- FastAPI `BackgroundTasks`로 비동기 실행 (API 응답을 블로킹하지 않음).
- 참조: `docs/internal/ref/dagster-reload-mechanism.md`
