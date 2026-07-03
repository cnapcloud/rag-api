# US-34 — Connector Abort/Delete Guard가 QUEUED/STARTING Dagster Run을 놓치는 버그

## Status
todo

## Symptom

커넥터 sync를 abort하거나, abort 직후 KB/커넥터를 삭제해도 일부 문서에서 백그라운드 인제스트가
계속 진행되어 `Aborted`로 표시된 문서가 나중에 다시 `indexed`로 뒤집히거나, Qdrant에 좀비 청크가
남는 경우가 있다.

## Root Cause

`event_queue_sensor.py:139` — `set_processing(doc_id)`가 `RunRequest`를 yield하기 *전*에 호출되며,
이 시점에는 `run_id=""` 상태다. 실제 Dagster `run_id`는 run이 QUEUED -> STARTING을 거쳐
`validate_op`가 실행될 때(`ingest_ops.py:48 set_processing(config.doc_id, run_id=context.run_id)`)에야
Postgres에 기록된다.

```
sensor yield RunRequest -> [QUEUED] -> [STARTING] -> validate_op 실행 (run_id 기록)
                            └────────────── 이 구간: run_id="" ──────────────┘
```

`connectors.py` `abort_sync()`:

```python
run_ids = {d["run_id"] for d in docs if d["status"] == "running" and d.get("run_id")}
```

`and d.get("run_id")` 조건 때문에 이 구간(QUEUED/STARTING)에 있는 run은 종료 대상에서 빠진다.
`terminate_dagster_run()`이 호출되지 않고, 문서는 `set_failed(doc_id, "Aborted")`로 표시되지만
실제 Dagster run은 계속 실행되어 나중에 `set_indexed`/`set_failed`로 Aborted 상태를 덮어쓴다.

KB/커넥터 delete guard(`kb.py`, `connectors.py`의 `sync_status == "running"` 체크)는 이 자체는
문제 없이 동작하지만, guard 통과 후 실제 삭제가 일어나기 전에 같은 구간의 run이 존재하면
`abort_sync()`와 동일한 문제가 발생할 수 있다.

`terminate_dagster_run()` 자체는 `MARK_AS_CANCELED_IMMEDIATELY` 정책 덕분에 QUEUED/STARTING
상태도 정상적으로 종료시킬 수 있음을 Dagster 소스(`terminate_pipeline_execution`)로 확인함 —
문제는 "이 함수가 호출되지 않는다"는 쪽.

같은 `run_id=""` 상태(dispatch lock 구간)를 다루는 [US-06](../US-06-sensor-dispatch-lock-false-zombie.md)과
근본 원인이 겹친다. US-06을 먼저 해결하면 이 구간의 의미가 더 명확해질 수 있다.

## Solution (안)

Postgres의 지연 기록된 `run_id` 컬럼에 의존하지 않고, Dagster GraphQL에서 `doc_id` 태그로
활성 run을 직접 조회한다.

- `dagster_utils.py`에 `find_active_run_ids_by_doc_ids(doc_ids: list[str]) -> list[str]` 추가
  — `runsOrError(filter: {tags: [...], statuses: [QUEUED, STARTING, STARTED, CANCELING]})` 쿼리
- `abort_sync()`에서 `status == "running"` 문서 전체(`run_id` 유무 무관)에 대해 이 조회 결과를
  합쳐서 종료 대상에 포함

## Known Limitation (해결 범위 밖)

센서 한 틱 안에서 "Redis에서 이벤트 pop" 과 "RunRequest yield" 사이의 아주 짧은 순간에 abort가
끼어들면, 큐에서도 이미 빠졌고 Dagster run도 아직 생성되지 않아 취소할 대상 자체가 없다.
센서를 트랜잭션화하지 않는 한 근본적으로 막을 수 없는 서브초 단위 레이스이므로, 이번 항목의
해결 범위에서 제외하고 루트 `CLAUDE.md`에 known issue로 명시한다.

## Acceptance Criteria

1. `status="running"` + `run_id=""` (QUEUED/STARTING 구간)인 문서도 `abort_sync()`에서 Dagster
   run이 정상 종료된다.
2. 이미 종료된 run을 종료 시도해도 에러 없이 스킵된다 (`terminate_dagster_run()`의 기존 동작 유지).
3. 기존 테스트가 모두 통과한다.
4. 서브초 레이스 케이스는 `CLAUDE.md` 알려진 이슈 섹션에 명시된다.
