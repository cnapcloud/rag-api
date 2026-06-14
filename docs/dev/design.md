# Internal Design

내부 데이터 구조, 상태 정의, 시스템 흐름에 대한 설계 문서.
엔드포인트 계약(스키마, 파라미터)은 `/docs` (Swagger UI) 참고.
API 사용법(curl 예시)은 [guide/api-guide.md](../guide/api-guide.md) 참고.

---

## 1. 문서 상태 (status)

| 값 | 의미 |
|----|------|
| `pending` | 큐에 대기 중 |
| `running` | 파이프라인 처리 중 |
| `indexed` | 인덱싱 완료 |
| `failed` | 파이프라인 실패 |
| `deleting` | 삭제 진행 중 |

### 상태 전이

```
업로드
  └─ running → indexed   (정상)
             → failed    (에러)

삭제 요청
  └─ deleting → (삭제 완료, Redis에서 제거)

recover API (status=running 전용)
  └─ running → failed → running (재큐잉)
```

---

## 2. Redis 키 구조

```
kbs                                 # KB 목록 (Set)

kb:{kb_id}                          # KB 메타데이터 (Hash)
    description
    status
    created_at

docs:{kb_id}                        # KB 내 문서 키 목록 (Set)

doc:{kb_id}:{object_key}            # 문서 상태 (Hash)
    status                          # running | indexed | failed | deleting
    etag
    run_id
    created_at                      # 최초 업로드 시점 (불변, hsetnx로 설정)
    updated_at                      # 마지막 상태 변경 시점
    chunk_count
    file_size
    doc_type
    embedding_model
    error

rag:upload:queue                    # 인제스트 이벤트 큐 (List)
rag:delete:queue                    # 삭제 이벤트 큐 (List)
rag:upload:delay                    # 인제스트 딜레이 큐 (Sorted Set, score=ready_at)
rag:delete:delay                    # 삭제 딜레이 큐 (Sorted Set, score=ready_at)
```

---

## 3. Qdrant Payload 스키마

```python
{
    "kb_id":              str,   # "kb-01"
    "doc_key":            str,   # "{kb_id}::{object_key}"
    "doc_type":           str,   # "pdf" | "docx" | "txt" | "md" | "hwp"
    "object_key":         str,   # "doc.pdf"
    "chunk_index":        int,
    "page_num":           int | None,
    "total_chunks":       int,
    "text":               str,
    "embedding_model":    str,   # "bge-m3"
    "embedding_provider": str,   # "ollama" | "openai"
    "chunk_strategy":     str,   # "recursive" | "semantic"
    "chunk_size":         int,
    "chunk_overlap":      int,
    "updated_at":         str,   # ISO 8601
}
```

컬렉션 구성: Dense (`cosine`) + Sparse (`IDF modifier`)

---

## 4. 검색 흐름

```
POST /api/search
    │
    ├─ KB별 병렬 Hybrid Search (Qdrant Dense + Sparse)
    │
    ├─ 복수 KB 결과 RRF 머지
    │
    ├─ Reranker (Jina) — enabled=true인 경우
    │       실패 시 → RRF 스코어 순 fallback
    │
    └─ top_n 반환
```

---

## 5. HTTP 에러 코드

| Status | 예외 클래스 | 발생 조건 |
|--------|-------------|-----------|
| 404 | `NotFoundError` | KB 또는 문서 없음 |
| 409 | `ConflictError` | 이미 존재하는 KB, 복구 불가 상태 |
| 422 | `IngestValidationError` | 파일 크기 초과, 지원하지 않는 형식 |
| 500 | `ConfigError` | 설정 오류 (vector_size 불일치 등) |
| 502 | `S3Error` | S3 연결 실패 |
| 503 | `RedisError` | Redis 연결 실패 |

---

## 6. Delay 큐 동작 원리

sensor tick마다 delay 큐에서 `score <= now`인 항목을 꺼내 메인 큐로 이동한다.

```
ZRANGEBYSCORE rag:upload:delay 0 <now>
  → ZREM (delay 큐에서 제거)
  → LPUSH rag:upload:queue (메인 큐로 복귀)
```

메인 큐 소비 중 해당 문서가 이미 처리 중(`try_set_processing` 실패)이면:

```
ready_at = now + processing_delay_sec
ZADD rag:upload:delay {event: ready_at}
```

`processing_delay_sec`는 `settings.yaml`의 `ingestion.processing_delay_sec`로 설정.

---

## 7. Dagster sensor default_status 동작 원리

`event_queue_sensor`는 `default_status=DefaultSensorStatus.RUNNING`으로 선언되어 있다.

- 이 값은 센서가 Dagster DB에 **처음 등록될 때만** 적용된다.
- 한 번 저장된 상태는 재배포나 재시작으로 바뀌지 않는다.
- STOPPED로 바뀌는 경우는 수동 stop 또는 DB 초기화뿐이다.

DB 초기화 후 재배포하면 신규 등록으로 처리되어 자동으로 RUNNING 상태가 된다.

---

## 8. Dagster 로깅 동작 원리

`pipeline/ops/` 순수 함수들은 `logging.getLogger(__name__)`을 사용한다.
Dagster는 기본적으로 이 로거를 감시하지 않으므로 Dagster UI에 로그가 나타나지 않는다.

`dagster.yaml`의 `managed_python_loggers`에 등록하면 Dagster UI에서도 볼 수 있다.

| 방식 | Dagster UI 노출 | 사용 위치 |
|------|----------------|-----------|
| `context.log.info()` | 항상 | Dagster op 래퍼 (`dagster_pipeline/ops/`) |
| `logging.getLogger(__name__)` 기본 | X | 순수 함수 (`pipeline/ops/`) |
| `logging.getLogger(__name__)` + `managed_python_loggers` | O | 순수 함수, 설정 후 |
