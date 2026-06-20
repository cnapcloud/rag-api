# Plan: US-14 — pending 상태 구현

## Context

현재 이벤트가 Redis 큐에 push된 후 Worker가 수령하기 전까지 문서 상태가 변하지 않는다.
예: reindex 요청 직후에도 문서 status가 `indexed`로 남아 있어 "접수됐는지" 확인 불가.

목표: 이벤트가 큐에 들어가는 순간 `pending`으로 전환해 가시성 확보.
Option A — `running`/`deleting` 중에 새 이벤트가 오면 **상태 변경 없이** 큐에만 추가.
`requeue` 상태는 도입하지 않음 (design.md에서 이미 제거 완료).

---

## 변경 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `src/pipeline/ops/meta.py` | `set_pending()` 함수 추가 |
| `src/dagster_pipeline/sensors/event_queue_sensor.py` | `enqueue_upload_event`, `enqueue_delete_event`, `_drain_delay_queue` 수정 |
| `src/pipeline/queue_worker.py` | `_requeue_after_delay` 수정 |
| `src/api/routers/docs.py` | `recover_doc` — 직접 lpush → `enqueue_upload_event` 교체 |
| `docs/dev/data-schema.md` | status 값에 `pending` 추가 |
| `tests/unit/test_queue_worker.py` | `_requeue_after_delay` 테스트 업데이트 + pending 관련 케이스 추가 |
| `tests/unit/test_recover_api.py` | `set_pending` 패치 추가 |

---

## 구현 상세

### 1. `meta.py` — `set_pending()` 추가

```python
def set_pending(kb_id: str, doc_source: str) -> None:
    """Set status=pending when an ingest or delete event is enqueued."""
    postgres_infra.set_doc_status(
        kb_id,
        doc_source,
        {"status": "pending", "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    logger.info("Status set to pending: kb=%s key=%s", kb_id, doc_source)
```

`_ALLOWED_DOC_FIELDS`에 `"status"` 이미 포함돼 있으므로 추가 필요 없음.

---

### 2. `enqueue_upload_event()` / `enqueue_delete_event()` 수정

두 함수 모두 같은 패턴 적용:

```python
def enqueue_upload_event(kb_id, doc_source, etag, file_size=0, force=False):
    from infra import postgres as pg
    from pipeline.ops.meta import set_pending

    r = get_redis_client()
    payload = json.dumps({...})

    doc = pg.get_doc_status(kb_id, doc_source)
    current_status = doc.get("status", "") if doc else ""
    if current_status not in ("running", "deleting"):
        set_pending(kb_id, doc_source)   # Option A: 상태 변경 없음이면 pending 설정

    r.lpush(UPLOAD_QUEUE_KEY, payload)
```

`enqueue_delete_event`도 동일 패턴. `set_pending` 전에 반드시 `lpush` 전에 실행 (race condition 방지).

---

### 3. `_drain_delay_queue()` 수정 (Dagster sensor 경로)

delay sorted set에서 main queue로 이동 시 per-item 상태 체크:

```python
def _drain_delay_queue(r, delay_key: str, main_key: str) -> None:
    now = time.time()
    items = r.zrangebyscore(delay_key, 0, now)
    if not items:
        return
    r.zrem(delay_key, *items)
    for item in items:
        try:
            event = json.loads(item)
        except json.JSONDecodeError:
            r.lpush(main_key, item)
            continue
        kb_id = event.get("kb_id", "")
        doc_source = event.get("doc_source", "")
        if kb_id and doc_source:
            from infra import postgres as pg
            from pipeline.ops.meta import set_pending
            doc = pg.get_doc_status(kb_id, doc_source)
            current = doc.get("status", "") if doc else ""
            if current not in ("running", "deleting"):
                set_pending(kb_id, doc_source)
        r.lpush(main_key, item)
```

---

### 4. `_requeue_after_delay()` 수정 (QueueWorker 경로)

asyncio.sleep 후 re-push 시 상태 체크:

```python
async def _requeue_after_delay(self, queue_key: str, raw: str) -> None:
    from config.settings import get_settings
    from infra.redis import get_redis_client

    delay = get_settings().queue_poll.retry_interval_sec
    await asyncio.sleep(delay)

    try:
        event = json.loads(raw)
        kb_id = event.get("kb_id", "")
        doc_source = event.get("doc_source", "")
        if kb_id and doc_source:
            from infra import postgres as pg
            from pipeline.ops.meta import set_pending
            doc = pg.get_doc_status(kb_id, doc_source)
            current = doc.get("status", "") if doc else ""
            if current not in ("running", "deleting"):
                set_pending(kb_id, doc_source)
    except Exception as e:
        logger.warning("_requeue_after_delay status check failed: %s", e)

    get_redis_client().lpush(queue_key, raw)
```

---

### 5. `recover_doc` 수정

직접 `lpush` 제거 → `enqueue_upload_event` 사용. `set_failed` 후 상태가 `failed`이므로 `enqueue_upload_event`가 자동으로 `pending` 설정.

```python
@router.post("/kb/{kb_id}/docs/{source:path}/recover", status_code=202)
async def recover_doc(kb_id: str, source: str):
    from dagster_pipeline.sensors.event_queue_sensor import enqueue_upload_event
    from infra.postgres import get_doc_status
    from pipeline.ops.meta import set_failed

    data = get_doc_status(kb_id, source)
    if not data:
        raise NotFoundError(...)
    if data.get("status") != "running":
        raise ConflictError(...)
    set_failed(kb_id, source, "Manually recovered via API", run_id=data.get("run_id", ""))
    enqueue_upload_event(kb_id, source, etag=data.get("etag", ""), file_size=0, force=True)
    logger.info("Manual recover queued: kb=%s source=%s", kb_id, source)
    return {"kb_id": kb_id, "doc_source": source, "queued": True}
```

`import json`과 `from infra.redis import get_redis_client` 제거.

---

### 6. `data-schema.md` — status 값 테이블 업데이트

```
| `pending` | Queued — waiting for worker pickup |
| `running` | Ingest in progress |
| `indexed` | Ingest complete, chunks stored in Qdrant |
| `deleting` | Delete in progress |
| `failed` | Ingest or delete failed — see `error` column |
```

기본값 주석도 수정: `DEFAULT 'pending'` (현재는 `DEFAULT 'running'` — 실제 Postgres DDL은 migration 파일에 있으므로 data-schema.md 주석만 수정)

---

## 테스트 업데이트

### `test_queue_worker.py`

- `test_requeue_after_delay_pushes_back`: `infra.postgres.get_doc_status` 패치 추가 (return `None` → set_pending 호출 경로)
- `test_requeue_after_delay_still_running_no_pending`: 새 케이스 — status=running일 때 set_pending 미호출 확인

### `test_recover_api.py`

- `test_running_doc_returns_202_and_requeues`: `enqueue_upload_event` 내부에서 `set_doc_status`가 호출되므로 `infra.postgres.set_doc_status` 패치 추가 (또는 `pipeline.ops.meta.set_pending` 패치)

---

## 백로그/플랜 인덱스 업데이트 (구현 시 함께)

- `.claude/backlogs/backlog.md`: US-14 행 추가 (in-progress → done)
- `.claude/backlogs/todo/US-14-pending-status.md`: 요건 상세 파일 생성
- `.claude/plans/plan.md`: 14번 행 추가

---

## 검증

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_queue_worker.py tests/unit/test_recover_api.py -v
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ -v

# 원격 서버 수동 확인
curl -s http://192.168.0.181:8000/api/kb/kb-test/docs | python3 -m json.tool --no-ensure-ascii
# reindex 직후 status=pending 확인
curl -s -X POST "http://192.168.0.181:8000/api/kb/kb-test/reindex?force=false"
curl -s http://192.168.0.181:8000/api/kb/kb-test/docs | python3 -m json.tool --no-ensure-ascii
```
