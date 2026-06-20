# US-14 — pending 상태 구현

## 배경

이벤트가 Redis 큐에 push된 후 Worker가 수령하기 전까지 문서 status가 변하지 않는다.
예: reindex 요청 직후에도 `indexed`가 유지되어 사용자가 "접수됐는지" 확인 불가.

## 요건

1. 이벤트를 큐에 넣기 직전, 문서 상태를 `pending`으로 전환한다.
2. Option A — 해당 문서가 이미 `running`/`deleting` 중이면 상태 변경 없이 큐에만 추가한다.
3. `requeue` 상태는 도입하지 않는다.

## 적용 대상

| 경로 | 설명 |
|------|------|
| webhook (`POST /internal/s3-event`) | `enqueue_upload_event` / `enqueue_delete_event` 호출 |
| API reindex (`POST /api/kb/{id}/reindex`) | `enqueue_upload_event` 호출 |
| API recover (`POST /api/kb/{id}/docs/{src}/recover`) | 현재 직접 lpush → `enqueue_upload_event`로 교체 |
| QueueWorker `_requeue_after_delay` | asyncio 딜레이 후 re-push 시 상태 체크 |
| Dagster Sensor `_drain_delay_queue` | sorted set에서 main queue 복귀 시 상태 체크 |

## 상태 전이 (Option A)

```
신규/reindex/webhook 이벤트:
  doc status != running/deleting → pending → (worker 수령) → running → indexed/failed

running/deleting 중 동일 문서 재요청:
  큐에 이벤트만 추가, 상태 변경 없음
  현재 처리 완료 → indexed/failed
  requeue_after_delay 재시도 → pending → running
```

## 완료 조건

- [ ] `meta.py`에 `set_pending()` 함수 존재
- [ ] `enqueue_upload_event` / `enqueue_delete_event`가 running/deleting이 아닐 때 pending 설정
- [ ] `_requeue_after_delay` 재push 시 상태 체크 후 pending 설정
- [ ] `_drain_delay_queue` 재push 시 상태 체크 후 pending 설정
- [ ] `recover_doc`이 `enqueue_upload_event` 사용
- [ ] `data-schema.md` status 테이블에 `pending` 추가
- [ ] 단위 테스트 통과
