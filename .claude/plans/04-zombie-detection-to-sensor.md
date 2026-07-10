# Plan 04 — Zombie Detection을 Sensor로 이동

Covers: US-06

## Overview

zombie 복구 로직을 `validate_op`에서 `event_queue_sensor`로 이동한다.
`validate_op`의 zombie 체크를 제거하고, sensor가 dispatch 전에 Dagster run 생존 여부를 직접 확인한다.

## Changes

### 1. `dagster_pipeline/sensors/event_queue_sensor.py`

`try_set_processing()` 호출을 제거하고, 직접 상태를 보고 판단하는 로직으로 교체한다.

```python
# 기존
if not try_set_processing(kb_id, doc_source, etag=etag):
    r.zadd(UPLOAD_DELAY_KEY, {raw: ready_at})
    continue
yield RunRequest(...)

# 변경 후
from infra import redis as redis_infra
from rag_api.pipeline.ops.meta import set_failed, set_processing

prev = redis_infra.get_doc_status(kb_id, doc_source)
if prev:
    s = prev.get("status")
    if s == "deleting":
        r.zadd(UPLOAD_DELAY_KEY, {raw: ready_at})
        continue
    elif s == "running":
        prev_run_id = prev.get("run_id", "")
        if prev_run_id:
            run = context.instance.get_run_by_id(prev_run_id)
            if run is not None and not run.is_finished:
                # 진짜 실행 중 → delay
                r.zadd(UPLOAD_DELAY_KEY, {raw: ready_at})
                continue
            # Dagster run 종료 → zombie 복구 후 dispatch
            set_failed(kb_id, doc_source,
                       f"Recovered: previous run no longer active (run_id={prev_run_id})",
                       run_id=prev_run_id)
            logger.warning("Zombie run recovered: kb=%s key=%s prev_run_id=%s",
                           kb_id, doc_source, prev_run_id)
        # run_id="" → dispatch lock 잔류(job 미시작), 그냥 dispatch

set_processing(kb_id, doc_source, etag=etag)  # run_id는 여전히 "" — job 시작 전
yield RunRequest(...)
```

### 2. `dagster_pipeline/ops/ingest_ops.py`

`validate_op`에서 zombie 체크 블록 전체 제거.

```python
# 제거 대상 (44~70번 줄)
prev = redis_infra.get_doc_status(...)
if prev and prev.get("status") == "running":
    ...  # 이 블록 전체 삭제

# 유지
set_processing(config.kb_id, config.doc_source, etag=config.etag, run_id=context.run_id)
```

`set_failed`, `redis_infra` import도 더 이상 불필요하면 제거.

### 3. `pipeline/queue_worker.py`

queue_worker는 runner.py를 직접 호출하므로 Dagster context가 없다.
Dagster run 체크는 불가 → `try_set_processing` 유지하되, runner.py가 `set_processing(run_id="local")`으로 즉시 덮어쓰므로 오탐 없음.
**변경 없음.**

## 변경 없는 파일

| 파일 | 이유 |
|------|------|
| `pipeline/ops/meta.py` | `try_set_processing`, `is_doc_busy` 그대로 유지 |
| `pipeline/queue_worker.py` | Dagster context 없음, runner.py가 run_id 덮어씀 |
| `api/routers/docs.py` | 변경 없음 |

## Test Plan

1. **정상 업로드**: 신규 문서 업로드 → zombie ERROR/WARNING 로그 없음
2. **zombie 복구**: Redis에 `status=running, run_id=<종료된_run>` 수동 삽입 → sensor tick 후 `set_failed` 호출 확인, 이후 정상 ingest
3. **진짜 실행 중 중복 방지**: `status=running, run_id=<활성_run>` 상태에서 동일 문서 이벤트 → delay queue로 이동 확인
4. **dispatch lock 잔류 처리**: `status=running, run_id=""` 상태에서 이벤트 → delay 없이 dispatch 확인
5. 기존 단위 테스트 전체 통과

## Notes

- `event_queue_sensor`의 `context.instance`는 `SensorEvaluationContext`에서 사용 가능
- sensor 내 import는 함수 안으로 이동 (모듈 수준 import 피할 것)
- validate_op에서 `set_failed` import가 `ingest_failure_hook`에서도 쓰이므로 제거 전 확인
