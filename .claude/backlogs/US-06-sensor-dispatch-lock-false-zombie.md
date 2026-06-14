# US-06 — Sensor Dispatch Lock이 Zombie로 오탐되는 버그

## Symptom

배치 업로드 시 처음 업로드하는 문서에서도 아래 로그가 발생한다.

```
ERROR  validate_op — Pipeline failed: kb=kb-01 key=requirements.md
       error=Recovered: status=running with no run_id (stale record)
WARNING validate_op — Zombie run recovered (no run_id): kb=kb-01 key=requirements.md
```

인제스트는 정상 완료되지만, 매 문서마다 false alarm ERROR + 순간적인 `status=failed` 기록이 발생한다.

## Root Cause

zombie 복구 책임이 잘못된 위치(validate_op)에 있고, sensor의 dispatch lock과 실제 zombie가 동일한 상태(`status=running, run_id=""`)를 공유한다.

- sensor는 이중 dispatch 방지 lock으로 `try_set_processing(run_id="")` 호출 → Redis에 `status=running, run_id=""` 기록
- validate_op의 zombie 체크가 `run_id=""` 를 "구버전 stale 레코드"로 간주해 무조건 `set_failed()` 호출

zombie 복구(Dagster run 생존 확인)는 dispatch 전 sensor에서 해야 하지만, 현재는 dispatch 후 validate_op에서 하고 있다.

## Solution

zombie 복구 책임을 sensor로 이동한다.

**sensor (dispatch 전):**
- `status=running` + `run_id` 있음 → `context.instance.get_run_by_id()` 로 Dagster 확인
  - 살아있음 → delay (진짜 실행 중)
  - 죽었음 → zombie 복구 후 dispatch
- `status=running` + `run_id=""` → dispatch lock 잔류(job 미시작), 그냥 dispatch
- `status=deleting` → delay

**validate_op:**
- zombie 체크 제거
- `set_processing(run_id=context.run_id)` 만 하고 진행

## Acceptance Criteria

1. 처음 업로드하는 문서에 zombie ERROR / WARNING 로그가 발생하지 않는다.
2. 실제 zombie(`status=running` + `run_id` 있는데 Dagster run 종료)는 sensor에서 복구된다.
3. 진짜 실행 중인 문서에 대한 이중 dispatch가 방지된다.
4. 기존 테스트가 모두 통과한다.
