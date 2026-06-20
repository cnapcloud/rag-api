# Plan 03 — Stuck Processing Recovery

## Covers

US-05

## Approach

Dagster `validate_op` 진입 시, 해당 문서의 이전 `run_id`가 Dagster에서 더 이상 활성 상태가 아니면 `set_failed()`로 zombie 상태를 해소하고 새 처리를 진행한다.
또한 `status=processing` 문자열을 `status=running`으로 전면 변경하여 의미를 명확히 한다.

## Implementation Steps

### Step 1 — status 값 `processing` → `running` 전면 변경

모든 소스/테스트/문서에서 `"processing"` 문자열을 `"running"`으로 교체한다.

| File | 변경 내용 |
|------|----------|
| `src/pipeline/ops/meta.py` | `set_processing()` 저장값, `is_doc_busy()` 비교값 |
| `src/pipeline/ops/runner.py` | status 비교 문자열 |
| `tests/unit/test_queue_worker.py` | 픽스처 status 값 |
| `tests/unit/test_mcp_tools.py` | 픽스처 및 assertion |
| `tests/integration/test_concurrency_guard.py` | `set_doc_status` 호출 인자 |
| `tests/dagster/test_sensor.py` | hset 픽스처 status 값 |

문서(`operations.md`, `US-05`, `Plan 03` 내 코드 샘플 포함)도 동시 변경.

### Step 2 — validate_op: 진입 시 run_id 저장

`dagster_pipeline/ops/ingest_ops.py`의 `validate_op` 맨 앞에서 `set_processing()` 호출.
Dagster `context.run_id`를 사용하므로 항상 실제 Dagster run_id가 저장된다.

```python
# validate_op 진입 직후
set_processing(config.kb_id, config.doc_source,
               etag=config.etag, run_id=context.run_id)
```

### Step 3 — validate_op: 이전 run_id 활성 여부 확인

`set_processing()` 호출 전에 기존 상태를 읽어 zombie 여부를 판단한다.

```python
prev = redis_infra.get_doc_status(config.kb_id, config.doc_source)
if prev and prev.get("status") == "running":
    prev_run_id = prev.get("run_id", "")
    if prev_run_id:
        run = context.instance.get_run_by_id(prev_run_id)
        if run is None or run.is_finished:
            set_failed(
                config.kb_id,
                config.doc_source,
                f"Recovered: previous run no longer active (run_id={prev_run_id})",
                run_id=prev_run_id,
            )
```

### Step 4 — is_doc_busy() 흐름 확인

`try_set_processing()` (sensor/queue_worker)이 `is_doc_busy()` 를 통해 차단되는 경로 확인.
Step 3에서 `set_failed()` 호출 후 `is_doc_busy()` 가 False를 반환하는지 검증.

### Step 5 — recover API 엔드포인트

`POST /api/kb/{kb_id}/docs/{key}/recover` 추가.

- `status=running`이면 `set_failed()` 후 `rag:upload:queue`에 재삽입 → 재처리 시작
- 다른 상태이면 409 반환

```python
# docs.py
@router.post("/kb/{kb_id}/docs/{key:path}/recover", status_code=202)
async def recover_doc(kb_id: str, key: str):
    from infra.redis import get_doc_status, get_redis_client
    from pipeline.ops.meta import set_failed
    import json

    data = get_doc_status(kb_id, key)
    if not data:
        raise NotFoundError(f"Document not found: kb={kb_id} key={key}")
    if data.get("status") != "running":
        raise ConflictError(
            f"Document is not in a recoverable state: status={data.get('status')}"
        )
    set_failed(kb_id, key, "Manually recovered via API", run_id=data.get("run_id", ""))
    event = json.dumps({"kb_id": kb_id, "doc_source": key, "etag": data.get("etag", ""), "force": True})
    get_redis_client().lpush("rag:upload:queue", event)
    return {"kb_id": kb_id, "doc_source": key, "queued": True}
```

### Step 6 — 테스트

`tests/dagster/test_validate_op_recovery.py` 작성:
- `status=running` + 완료된 run_id → `set_failed` 호출 확인
- `status=running` + 활성 run_id → 차단 유지 확인
- `status=running` + run_id 없음 → set_failed 호출 확인 (run_id 부재 = 이전 sensor 기록)
- `status=indexed` → 복구 로직 미실행 확인

`tests/unit/test_recover_api.py` 작성:
- `status=running` → 202, upload 큐 재삽입 확인
- `status=indexed` → 409 반환 확인
- 존재하지 않는 문서 → 404 반환 확인

## Files to Change

| File | Change |
|------|--------|
| `src/pipeline/ops/meta.py` | `"processing"` → `"running"` |
| `src/pipeline/ops/runner.py` | `"processing"` → `"running"` |
| `src/dagster_pipeline/ops/ingest_ops.py` | validate_op에 zombie 감지 + set_processing 호출 추가 |
| `src/api/routers/docs.py` | recover 엔드포인트 추가 |
| `tests/unit/test_queue_worker.py` | `"processing"` → `"running"` |
| `tests/unit/test_mcp_tools.py` | `"processing"` → `"running"` |
| `tests/integration/test_concurrency_guard.py` | `"processing"` → `"running"` |
| `tests/dagster/test_sensor.py` | `"processing"` → `"running"` |
| `tests/dagster/test_validate_op_recovery.py` | 신규 테스트 파일 |
| `tests/unit/test_recover_api.py` | 신규 테스트 파일 |

## Files NOT Changed

- `src/pipeline/ops/validate.py` — 순수 함수 유지
- `src/infra/redis.py` — 변경 없음

## Constraints

- `validate()` 순수 함수에 Dagster instance 조회 추가 금지
- zombie 감지 로직은 `validate_op` 래퍼에만 위치
- 복구 후 새 처리는 정상 흐름 그대로 진행 (별도 분기 없음)
