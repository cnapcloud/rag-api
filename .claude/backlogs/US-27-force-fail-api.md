---
id: US-27
title: Force Fail API — 진행 중 문서 강제 실패 처리 + Dagster job terminate
status: done
---

# US-27 Force Fail API

## 목표

운영자가 `running` / `deleting` / `pending` 상태로 stuck된 문서를 강제로 `failed`로 전환할 수 있는 API 제공.
Dagster job이 살아 있으면 force terminate.

## 엔드포인트

```
POST /api/kb/{kb_id}/docs/{doc_id}/fail
```

**Query parameter:**
- `reason: str` (optional, 기본값: `"Manually failed via API"`) → `error` 필드에 저장 (최대 500자)

**허용 상태:** `uploading`, `pending`, `running`, `deleting`
**결과 상태:** `failed`
**재큐:** 없음

## 동작

1. doc 조회 → status 검증 (허용 상태 아니면 ConflictError)
2. `run_id` 있으면 Dagster job force terminate
3. `set_failed(doc_id, reason, run_id=doc.run_id)` 호출

## 제약 사항

1. **pending 상태 Redis 이벤트 잔류**
   - `pending` 문서는 Redis 큐(List) 또는 delay 큐(Sorted Set)에 이벤트가 남아 있음
   - force-fail 시 `LREM` / `ZREM`으로 제거

2. **queue_worker 모드에서 terminate 수단 없음**
   - Dagster job 없이 asyncio task로 실행되므로 task를 외부에서 종료할 방법이 없음

## 처리 방안

1. `pending` 잔류 이벤트 → `LREM`(upload queue) + `ZREM`(delay queue)으로 제거. force=false/true 두 변형 모두 처리
2. Dagster terminate → `settings.dagster.endpoint/graphql` 의 `terminateRun(terminatePolicy: MARK_AS_CANCELED_IMMEDIATELY)` mutation 호출. active run이 발견된 경우 terminate 실패 시 API 에러로 전파 (set_failed 미수행). run이 이미 종료된 경우는 무시
3. queue_worker 모드 → terminate 스킵, `set_failed`만 수행
4. `run_id` → `set_failed` 호출 시 그대로 전달 (감사 목적)

## 추가 구현 (2026-06-28)

### queue_worker 모드 경고 로그 + UI 피드백

queue_worker 모드에서 `running`/`deleting` 상태 문서에 force-fail을 적용할 때, asyncio 태스크를 실제로 종료할 수 없으므로:

- `api/routers/docs.py`: `queue_worker.enabled` && status in (`running`, `deleting`) 조건에서
  - WARNING 로그: "Force fail set but background task cannot be terminated in queue_worker mode"
  - 응답에 `warning` 필드 추가: "Status set to failed, but the background task is still running..."
- `api/docs.ts`: 반환 타입에 `warning?: string` 추가
- `components/DocDetailPanel.tsx`: `warning` 필드가 있으면 "Force fail requested — task may still be running" destructive 토스트, 없으면 기존 "Document force-failed" 토스트
