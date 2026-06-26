# Plan 19 — Connector Dagster Schedule dynamic registration (R-12)

**Covers**: US-19  
**Status**: done

---

## 목표

커넥터별 cron 스케줄을 Dagster ScheduleDefinition으로 동적 등록.
워크스페이스 시작 시 DB를 조회해 스케줄 목록을 빌드하고,
`schedule_enabled` 토글은 재시작 없이 런타임 DB 재조회로 반영.

---

## 영향 범위

| 파일 | 변경 |
|------|------|
| `src/defs/schedules/connector_schedules.py` | 신규 — `_make_connector_schedule`, `load_connector_schedules` |
| `src/defs/definitions.py` | `schedules=load_connector_schedules()` 추가 |
| `.claude/backlogs/backlog.md` | US-19 행 추가 |
| `.claude/plans/plan.md` | plan 19 행 추가 |

---

## 설계 결정

### 1. 동적 등록 vs 정적 등록

Dagster는 `Definitions` 객체 생성 시점에 스케줄 목록을 고정한다.
커넥터가 새로 추가될 때마다 워크스페이스를 재로드해야 새 스케줄이 등록된다.
이 제약은 Dagster 아키텍처 상 불가피하며 요구사항(R-12)에도 명시됨.

### 2. schedule_enabled 토글 즉시 반영

`execution_fn` 내부에서 매 firing마다 DB를 다시 조회해 `schedule_enabled`를 확인한다.
`false`면 `SkipReason`을 반환해 실제 run이 생성되지 않도록 처리.
워크스페이스 재시작 없이 토글이 즉시 반영됨.

```python
def execution_fn(context):
    c = get_connector(connector_id)
    if not c.get("schedule_enabled"):
        return SkipReason(f"Schedule disabled: {connector_id}")
    ...
    return RunRequest(run_key=..., run_config=..., tags=...)
```

### 3. run_key 중복 방지

`run_key = f"{connector_id}-{context.scheduled_execution_time.isoformat()}"` 로 설정.
같은 스케줄 구간에 중복 firing이 발생해도 동일 run_key면 Dagster가 무시.

### 4. DB 장애 시 Graceful degradation

`load_connector_schedules()`에서 예외 발생 시 경고 로그만 남기고 빈 목록 반환.
Dagster 워크스페이스 로드 실패를 방지.

---

## 구현 흐름

```
Dagster 워크스페이스 로드
  → definitions.py: load_connector_schedules() 호출
    → infra/postgres: list_connectors(has_schedule=True)
    → 커넥터마다 _make_connector_schedule(c) 호출
      → ScheduleDefinition(name, cron_schedule, job, execution_fn) 생성
  → Definitions(schedules=[...]) 등록

cron 시각 도달 시
  → execution_fn(context) 호출
    → DB 재조회: schedule_enabled, status 확인
    → OK면 RunRequest 반환
    → connector_sync_job 실행 → connector_sync_op
```
