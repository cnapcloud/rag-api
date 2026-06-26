---
id: US-22
title: deleting 상태 문서의 ingest/delete 이벤트 즉시 버림
status: in-progress
---

## 배경

현재 Sensor와 QueueWorker는 `status=running`과 `status=deleting`을 동일하게 취급하여, 두 경우 모두 이벤트를 delay queue로 보낸다. 그러나 `deleting` 상태의 문서에 대한 ingest 이벤트는 재시도해도 의미가 없다 — 삭제 완료 후 S3 오브젝트가 없거나 문서 상태가 유효하지 않으므로 validate/parse 단계에서 어차피 실패한다. `deleting` 상태에서 들어온 delete 이벤트 역시 중복 delete이므로 버리는 것이 맞다.

## 요건

### Sensor (`event_queue_sensor.py`)

- upload 이벤트 처리 중 문서 status == `deleting` → warning 로그 + 즉시 discard (continue)
- delete 이벤트 처리 중 문서 status == `deleting` → warning 로그 + 즉시 discard (continue)
- `_is_blocked_by_active_run`에서 `deleting` 조건 제거 — `running` 상태만 처리
- `running` 상태 동작(run_id 확인 → 활성이면 delay, zombie면 복구)은 변경 없음

### QueueWorker (`queue_worker.py`)

- upload 이벤트: `deleting` → warning 로그 + discard / `running` → delay queue (기존 유지)
- delete 이벤트: `deleting` → warning 로그 + discard / `running` → delay queue (기존 유지)

## 완료 기준

- `deleting` 상태 문서에 대한 upload/delete 이벤트가 delay queue에 쌓이지 않음
- warning 로그에 `doc_id` 포함
- `running` 상태 동작 회귀 없음
- 관련 단위 테스트 통과
