---
id: US-28
title: Force Delete — indexed 문서 hard delete + outdated 자동 force 처리
status: done
---

# US-28 Force Delete

## 목표

`DELETE /api/kb/{kb_id}/docs/{doc_id}?force=true` 파라미터 추가.
`force=true`이면 `indexed` 상태여도 soft delete 대신 hard delete(S3 + DB row 제거) 수행.
Admin UI에서 `outdated` 문서 삭제 시 자동으로 `force=true` 사용.

## 동작

| 조건 | Qdrant | S3 | DB |
|------|--------|----|----|
| `indexed` + `force=false` (기존) | 청크 삭제 | 보존 | status=deleted (soft) |
| `indexed` + `force=true` | 청크 삭제 | 삭제 | row 제거 (hard) |
| 그 외 + any force | 청크 시도 | 삭제 | row 제거 (hard) |

## 변경 범위

**Backend**
- `pipeline/ops/delete.py` — `delete_doc(force=False)`, `_delete_s3_object`, `_delete_db_record`에 force 반영
- `pipeline/ops/runner.py` — `run_delete_pipeline(force=False)`
- `pipeline/enqueue.py` — `enqueue_delete_event(force=False)`, 큐 payload에 force 포함
- `pipeline/queue_worker.py` — delete event에서 force 읽어 `run_delete_pipeline`에 전달
- `defs/ops/delete_ops.py` — `DeleteConfig`에 `force: bool = False` 추가
- `defs/sensors/event_queue_sensor.py` — delete 이벤트 force를 Dagster run config에 전달
- `api/routers/docs.py` — `DELETE` 엔드포인트에 `force: bool = Query(False)` 추가

**Frontend (rag-admin)**
- `api/docs.ts` — `delete(kbId, docId, force=false)` 파라미터 추가
- `components/DocDetailPanel.tsx` — `outdated` 문서 삭제 시 `force=true` 자동 전달
