---
plan: 27
title: Force Fail API — 진행 중 문서 강제 실패 처리
covers: US-27
status: todo
---

# Plan 27 — Force Fail API

## 변경 파일

| 파일 | 변경 내용 |
|------|---------|
| `src/api/routers/docs.py` | `POST /kb/{kb_id}/docs/{doc_id}/fail` 엔드포인트 추가 |
| `src/infra/dagster_utils.py` | `terminate_dagster_run(run_id)` 헬퍼 신규 |
| `tests/unit/test_force_fail_api.py` | 엔드포인트 단위 테스트 |

## 구현 단계

### 1. `src/infra/dagster_utils.py` 신규

Dagster는 원격 서버로 실행되므로 `DagsterInstance.get()` 불가.
`settings.dagster.endpoint` (e.g. `http://localhost:3000`)의 GraphQL API로 terminate.

```python
_TERMINATE_MUTATION = """
mutation TerminateRun($runId: String!) {
  terminateRun(runId: $runId, terminatePolicy: MARK_AS_CANCELED_IMMEDIATELY) {
    __typename
    ... on TerminateRunSuccess { run { runId } }
    ... on TerminateRunFailure { message }
    ... on RunNotFoundError { runId }
  }
}
"""


def terminate_dagster_run(run_id: str) -> None:
    """Force-terminate a Dagster run via GraphQL API.

    No-op if run not found or already finished. Raises RuntimeError if termination fails.
    """
    from config.settings import get_settings
    cfg = get_settings()

    if cfg.queue_worker.enabled:
        logger.info("Queue worker mode: Dagster terminate skipped run_id=%s", run_id)
        return

    import httpx
    url = f"{cfg.dagster.endpoint}/graphql"
    resp = httpx.post(url, json={"query": _TERMINATE_MUTATION, "variables": {"runId": run_id}}, timeout=5.0)
    resp.raise_for_status()
    data = resp.json().get("data", {}).get("terminateRun", {})
    typename = data.get("__typename", "")
    if typename == "TerminateRunSuccess":
        logger.info("Dagster run force-terminated: run_id=%s", run_id)
        return
    if typename == "RunNotFoundError":
        logger.info("Dagster run not found (already finished): run_id=%s", run_id)
        return
    raise RuntimeError(f"Dagster force-terminate failed: run_id={run_id} reason={data.get('message', typename)}")
```

### 2. `src/pipeline/enqueue.py` — `_dequeue_upload_events` 추가

```python
def dequeue_upload_events(doc_id: str) -> None:
    """Remove all upload events for doc_id from upload queue and delay queue."""
    import json
    from infra.redis import get_redis_client
    from pipeline.enqueue import UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY

    r = get_redis_client()
    for force in (False, True):
        payload = json.dumps({"doc_id": doc_id, "force": force})
        r.lrem(UPLOAD_QUEUE_KEY, 0, payload)
        r.zrem(UPLOAD_DELAY_KEY, payload)
```

### 3. `src/api/routers/docs.py` 엔드포인트 추가

```python
@router.post("/kb/{kb_id}/docs/{doc_id}/fail", status_code=200)
async def force_fail_doc(
    kb_id: str,
    doc_id: str,
    reason: str = Query(default="Manually failed via API"),
):
    from exceptions import ConflictError
    from infra.dagster_utils import terminate_dagster_run
    from infra.postgres import get_doc_by_id
    from pipeline.ops.meta import set_failed

    doc = get_doc_by_id(doc_id)
    if doc is None or doc.get("kb_id") != kb_id:
        raise NotFoundError(f"Document not found: kb={kb_id} doc_id={doc_id}")

    status = doc.get("status", "")
    if status not in ("uploading", "pending", "running", "deleting"):
        raise ConflictError(
            f"Document cannot be force-failed in current state: status={status}"
        )

    run_id = doc.get("run_id") or ""
    if run_id:
        terminate_dagster_run(run_id)

    if status == "pending":
        _dequeue_upload_events(doc_id)

    set_failed(doc_id, reason[:500], run_id=run_id)
    logger.info("Force fail applied: kb=%s doc_id=%s status_was=%s", kb_id, doc_id, status)
    return {"kb_id": kb_id, "doc_id": doc_id, "status": "failed"}
```

### 3. 테스트 (`tests/unit/test_force_fail_api.py`)

커버할 케이스:
- `uploading` → failed (run_id 없음 → terminate 스킵)
- `pending` → failed + Redis 이벤트 제거 (run_id 있으면 terminate 호출, 없으면 스킵)
- `running` → failed (run_id 있음 → terminate 호출)
- `deleting` → failed (run_id 있음 → terminate 호출)
- `indexed` → ConflictError
- `failed` → ConflictError
- doc 없음 → NotFoundError
- GraphQL 호출 실패 (네트워크 오류) → log warning만, set_failed는 정상 수행
- queue_worker 모드 → terminate 스킵

테스트에서 `httpx.post`는 `unittest.mock.patch`로 mock.

## 주의사항

- Dagster는 원격 서버 — `DagsterInstance.get()` 사용 금지, GraphQL API만 사용.
- terminate 실패(네트워크 오류, run 이미 종료 등)는 warning 로그만, `set_failed`는 항상 수행.
- `pending` 상태 문서는 Redis 큐 이벤트가 잔류할 수 있음 — API 응답에 `warning` 필드로 안내.
- `httpx`는 기존 의존성 확인 필요 (`requirements.txt` 또는 `pyproject.toml`).
