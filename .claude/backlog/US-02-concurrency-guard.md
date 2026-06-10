# US-02: Delete/Ingest 동시 실행 경쟁 조건 해결

## 문제

delete ↔ ingest가 동시에 실행될 때 조율 메커니즘이 없어 아래 문제가 발생한다.
Dagster 모드(`event_queue_sensor`)와 비-Dagster 모드(`QueueWorker`) 양쪽에서 동일하게 발생한다.

- ingest 진행 중 delete가 실행되면 delete 완료 후 ingest가 Qdrant/Redis를 복원 → 삭제 무효화
- run_key가 ETag + force를 포함해 `force=True` 재사용 시 두 번째부터 스킵됨 (Dagster 모드)
- `status=processing` 체크가 잡 내부(validate_op)에서 발생 → 디스패치 후라 늦음
- delete 잡에 run_key 없어 중복 삭제 잡 생성 가능 (Dagster 모드)
- QueueWorker는 processing 체크 없이 즉시 create_task → 동일 경쟁 조건 노출

## 요건

1. run_key는 항상 유일 (UUID) — event dedup만 담당 (Dagster 모드)
2. 디스패치 레이어(센서/QueueWorker)가 이벤트를 꺼낼 때 **작업 중 여부(`is_doc_busy`)** 확인 후 상태 설정 → 잡/태스크 생성
   - upload 이벤트: `try_set_processing()` — busy면 False 반환
   - delete 이벤트: `try_set_deleting()` — busy면 False 반환
3. busy 상태(`processing` 또는 `deleting`)이면 지연 후 재판단 — 지연 시간은 `ingestion.processing_delay_sec` 설정값 사용
   - Dagster 모드: Redis sorted set 지연 큐 (rag:upload:delay / rag:delete:delay)
   - QueueWorker 모드: asyncio.sleep 후 Redis 큐 재투입
4. 상태 전환 정의
   - ingest 시작: `processing` → 완료: `indexed` / 실패: `failed`
   - delete 시작: `deleting` → 완료: 메타 전체 제거 / 실패: `failed`
5. validate는 ETag + 파일 크기 체크만 담당 (processing 체크 제거)
   - ETag 동일 + force=False → status를 processing → indexed로 복원 후 skip (no-op)
   - 디스패치 레이어가 set_processing을 먼저 하므로 반드시 indexed로 복원해야 함
   - ETag 다름 or force=True → 파이프라인 진행
6. 공통 결정 로직을 `meta.py`에 추출: `is_doc_busy()` / `try_set_processing()` / `try_set_deleting()` / `restore_indexed()`

## 인수 조건

- force=True 연속 2회 → 두 번 모두 실행됨 (순차, 지연 허용)
- ingest 진행 중 delete 요청 → `processing_delay_sec` 후 실행
- delete 진행 중 ingest 요청 → `processing_delay_sec` 후 실행
- ETag 동일 재업로드 → skip 후 status=indexed 복원
- delete 완료 후 동일 파일 재업로드 → 정상 ingest
