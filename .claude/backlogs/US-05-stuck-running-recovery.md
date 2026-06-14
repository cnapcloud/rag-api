# US-05 — Stuck Running 자동 복구

## Problem

서버(Dagster worker / FastAPI)가 문서 처리 중 비정상 종료되면 Redis에 `status=running`이 남는다.
이후 같은 문서를 재업로드하면 `is_doc_busy()` 가 True를 반환하여 새 처리가 영구 차단된다.

## Acceptance Criteria

1. Dagster 파이프라인이 시작될 때 해당 문서의 `run_id`와 `status=running`을 Redis에 저장한다.
2. 같은 문서에 대해 `validate_op`가 다시 실행될 때, 저장된 `run_id`가 Dagster에서 더 이상 활성 상태가 아니면 `status=failed`로 전환하고 새 처리를 진행한다.
3. 복구는 해당 문서에 대해서만 수행한다 (전체 스캔 없음).
4. Dagster 경로에만 적용 (runner.py 경로는 별도).
5. `POST /api/kb/{kb_id}/docs/{key}/recover` API를 제공한다. 호출 시 해당 문서가 `status=running`이면 `status=failed`로 전환한 뒤 `rag:upload:queue`에 재삽입하여 재처리를 시작한다. 다른 상태이면 409를 반환한다.

## Out of Scope

- runner.py / queue_worker 경로의 복구
- 재업로드 없이 자동으로 복구되는 background sweep
- TTL / heartbeat 기반 메커니즘

## Notes

- `set_failed()`, `list_docs_by_status()` 는 이미 구현되어 있음
- `set_running()` 은 이미 `run_id` 필드를 저장함
- 복구는 lazy — 같은 문서가 재업로드될 때만 발생함
