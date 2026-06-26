# US-19 — Connector Dagster Schedule dynamic registration (R-12)

## Summary

커넥터별 cron 스케줄을 Dagster ScheduleDefinition으로 동적 등록.
`sync_schedule`이 설정된 커넥터를 DB에서 읽어 워크스페이스 시작 시 자동 등록.
`schedule_enabled` 토글은 재시작 없이 즉시 반영.

## Acceptance Criteria

1. `load_connector_schedules()` 호출 시 `sync_schedule IS NOT NULL`인 커넥터를 DB에서 조회해 `ScheduleDefinition` 목록 반환
2. 스케줄 이름: `connector_sync_{connector_id}` (hyphen → underscore)
3. `execution_fn` 런타임에 DB를 다시 조회하여 `schedule_enabled=false` 또는 `status=paused`면 `SkipReason` 반환 — 워크스페이스 재시작 불필요
4. `run_key` = `{connector_id}-{scheduled_execution_time.isoformat()}` — 동일 실행 구간 중복 방지
5. `connector_sync_job`에 연결되며 `run_config.ops.connector_sync_op.config.connector_id` 전달
6. `tags`: `connector_id`, `trigger=schedule`
7. DB 연결 실패 시 경고 로그만 남기고 빈 목록 반환 — Dagster 시작 실패 방지
8. `Definitions(schedules=load_connector_schedules())` 로 등록

## Design Notes

- `schedule_enabled` 변경은 재시작 없이 적용 (`execution_fn`이 매 firing마다 DB 재조회)
- `sync_schedule` 자체(cron 표현식) 변경은 워크스페이스 재로드 필요 (Dagster 스케줄 정의 시점에 고정)
- 수동 sync (`POST /sync`)는 `schedule_enabled` 상태와 무관하게 항상 허용
- Dagster Schedule과 수동 트리거는 동일한 `connector_sync_job` → `connector_sync_op` 경로 공유

## Dependencies

- US-16 (Connector CRUD + Sync API) — done
- US-18 (WebConnector), US-20 (ConfluenceConnector), US-21 (GitHubConnector) — done
