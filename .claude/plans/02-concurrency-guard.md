# Plan 02: Concurrency Guard — Sensor + QueueWorker

Covers: US-02
Status: done

## 변경 파일

| 파일 | 변경 내용 |
|------|----------|
| `src/pipeline/ops/meta.py` | `is_doc_busy()`, `set_deleting()`, `try_set_processing()`, `try_set_deleting()`, `restore_indexed()` |
| `src/pipeline/ops/validate.py` | processing 체크 제거, ETag + 파일 크기 체크만 유지 |
| `src/dagster_pipeline/sensors/event_queue_sensor.py` | 지연 큐 drain, try_set_processing/try_set_deleting, UUID run_key |
| `src/dagster_pipeline/ops/ingest_ops.py` | set_processing 제거, ETag skip 시 restore_indexed 호출 |
| `src/pipeline/queue_worker.py` | try_set_processing/try_set_deleting 체크, asyncio.sleep 후 재투입 |
| `src/pipeline/ops/runner.py` | run_ingest_from_key skip 경로 restore_indexed, run_delete_pipeline set_deleting 추가 |

## 공통 로직 (meta.py)

```python
def is_doc_busy(kb_id, object_key) -> bool:
    """Returns True if document has an in-progress operation (processing or deleting)."""
    status = redis_infra.get_doc_status(kb_id, object_key)
    return bool(status and status.get("status") in ("processing", "deleting"))

def set_deleting(kb_id, object_key, run_id="") -> None:
    redis_infra.set_doc_status(kb_id, object_key, {"status": "deleting", "run_id": run_id})

def try_set_processing(kb_id, object_key, etag="", run_id="") -> bool:
    if is_doc_busy(kb_id, object_key):
        return False
    set_processing(kb_id, object_key, etag=etag, run_id=run_id)
    return True

def try_set_deleting(kb_id, object_key, run_id="") -> bool:
    if is_doc_busy(kb_id, object_key):
        return False
    set_deleting(kb_id, object_key, run_id=run_id)
    return True

def restore_indexed(kb_id, object_key, etag="") -> None:
    """ETag-skip 경로에서 processing → indexed 복원."""
    redis_infra.set_doc_status(kb_id, object_key, {"status": "indexed"})
    if etag:
        redis_infra.set_doc_etag(kb_id, object_key, etag)
```

## 상태 전환

```
ingest:  (없음/indexed/failed) → 센서/QW: set_processing
           → validate ETag 동일: restore_indexed → indexed
           → validate 통과: 파이프라인 진행 → indexed / failed

delete:  (없음/indexed/failed) → 센서/QW: set_deleting
           → 완료: delete_doc_meta (키 전체 제거)
           → 실패: set_failed → failed

is_doc_busy() = status in ("processing", "deleting")
  → 두 방향 모두 차단: ingest 중 delete 불가, delete 중 ingest 불가
```

## Dagster 모드 (event_queue_sensor.py)

### 지연 큐

| Redis Key | 타입 | 역할 |
|-----------|------|------|
| `rag:upload:delay` | Sorted Set | score = ready_at (Unix timestamp) |
| `rag:delete:delay` | Sorted Set | score = ready_at (Unix timestamp) |

### 센서 tick 흐름

```
tick 시작
  drain: ZRANGEBYSCORE delay_key 0 now → ZREM → LPUSH main_queue  (ZREM 필수)

  upload loop:
    rpop rag:upload:queue
    try_set_processing() → False? → ZADD rag:upload:delay (now + processing_delay_sec)
    yield RunRequest(run_key=uuid4())

  delete loop:
    rpop rag:delete:queue
    try_set_deleting() → False? → ZADD rag:delete:delay (now + processing_delay_sec)
    yield RunRequest(run_key=uuid4())
```

### ingest_ops.py validate_op

- set_processing 제거 (센서가 처리)
- validate False → restore_indexed 후 skip

## QueueWorker 모드 (queue_worker.py)

```
upload loop:
  try_set_processing() → False → _requeue_after_delay(UPLOAD_QUEUE_KEY, raw)
                       → True  → _run_ingest(event)

delete loop:
  try_set_deleting()   → False → _requeue_after_delay(DELETE_QUEUE_KEY, raw)
                       → True  → _run_delete(event)

_requeue_after_delay: asyncio.sleep(processing_delay_sec) → lpush queue_key raw
```

## runner.py

- `run_ingest_from_key` skip 경로: status=="processing" → restore_indexed
- `run_delete_pipeline`: 시작 시 set_deleting() 호출 (CLI 직접 실행 모드)

## 주의 사항

- TOCTOU (check → set 사이) 잔존. 단일 프로세스/이벤트루프 특성상 실용적 위험 낮음.
- 완전한 원자성 필요 시 Redis Lua 스크립트 별도 작업.
- drain 시 ZRANGEBYSCORE 후 반드시 ZREM (누락 시 매 tick 중복).
