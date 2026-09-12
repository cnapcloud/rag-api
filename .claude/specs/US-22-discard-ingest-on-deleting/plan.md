# Plan 22 — deleting 상태 이벤트 즉시 버림

Covers: US-22

## 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/defs/sensors/event_queue_sensor.py` | `_is_blocked_by_active_run`에서 `deleting` 제거 + 각 큐 루프에 사전 차단 추가 |
| `src/pipeline/queue_worker.py` | upload/delete 루프에서 `deleting`/`running` 조건 분리 |
| `tests/unit/test_event_queue_sensor.py` | 신규 또는 기존 파일에 deleting discard 케이스 추가 |
| `tests/unit/test_queue_worker.py` | 신규 또는 기존 파일에 deleting discard 케이스 추가 |

## 상세 구현

### 1. `event_queue_sensor.py` — `_is_blocked_by_active_run`

```python
# 변경 전
if s not in ("running", "deleting"):
    return False

# 변경 후
if s != "running":
    return False
```

### 2. `event_queue_sensor.py` — upload 큐 루프

```python
doc = get_doc_by_id(doc_id)
# 추가: deleting 사전 차단
if doc and doc.get("status") == "deleting":
    logger.warning("Upload event discarded: doc in deleting state: doc_id=%s", doc_id)
    continue
# 기존: running 체크
if doc and _is_blocked_by_active_run(...):
    continue
```

### 3. `event_queue_sensor.py` — delete 큐 루프

동일 패턴으로 `deleting` 사전 차단 추가.

### 4. `queue_worker.py` — upload 루프

```python
# 변경 전
if s in ("running", "deleting"):
    r.zadd(UPLOAD_DELAY_KEY, ...)

# 변경 후
if s == "deleting":
    logger.warning("Upload event discarded: doc in deleting state: doc_id=%s", doc_id)
    continue
if s == "running":
    r.zadd(UPLOAD_DELAY_KEY, ...)
```

### 5. `queue_worker.py` — delete 루프

```python
# 변경 전
if doc and doc.get("status") in ("running", "deleting"):
    r.zadd(DELETE_DELAY_KEY, ...)

# 변경 후
if doc:
    s = doc.get("status", "")
    if s == "deleting":
        logger.warning("Delete event discarded: doc in deleting state: doc_id=%s", doc_id)
        continue
    if s == "running":
        r.zadd(DELETE_DELAY_KEY, ...)
```

## 테스트 케이스

| 테스트 | 기대 동작 |
|--------|-----------|
| 센서: upload + deleting | delay queue 미호출, warning 로그 |
| 센서: delete + deleting | delay queue 미호출, warning 로그 |
| 센서: upload + running + 활성 run | delay queue 호출 (기존 회귀 없음) |
| 워커: upload + deleting | delay queue 미호출, warning 로그 |
| 워커: delete + deleting | delay queue 미호출, warning 로그 |
| 워커: upload + running | delay queue 호출 (기존 회귀 없음) |
