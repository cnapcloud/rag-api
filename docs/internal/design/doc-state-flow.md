# 문서 상태 흐름과 API 관계

## 1. 개요

문서(doc)는 단일 `status` 필드로 전체 생명주기를 표현한다.

| 상태 | 의미 | 분류 |
|------|------|------|
| `uploading` | S3 파일 전송 중 | 활성 |
| `pending` | Redis 큐 대기 중 | 활성 |
| `running` | 인제스트 파이프라인 실행 중 | 활성 |
| `deleting` | 삭제 파이프라인 실행 중 | 활성 |
| `indexed` | 인덱싱 완료 — 검색 가능 | 안정 |
| `failed` | 파이프라인 실패 — last_error 필드에 원인 기록 | 안정 |
| `deleted` | soft-delete 완료 — Qdrant 청크 제거, S3 파일 유지 | 안정 |
| `outdated` | dedup에 의해 구버전으로 판정됨 | 안정 |

활성 여부는 안정 상태의 여집합으로 정의한다.

```python
_STABLE_STATUSES = frozenset({"indexed", "failed", "deleted", "outdated"})

def is_active(status: str) -> bool:
    return status not in _STABLE_STATUSES
```

---

## 2. 상태 전이

### 전체 상태 전이도

```
  POST /upload ──(신규/재업로드)──► uploading ──(S3 전송 완료)──► pending
                                                                    │
                                                           (큐 워커 dequeue)
                                                                    │
                                                                    ▼
                                                                running
                                                                    │
                         ┌──────────────────────────────────────────┤
                         │                          │               │
                    인제스트 성공              dedup 판정       파이프라인 실패
                         │                          │               │
                         ▼                    (구버전 판정)          ▼
                     indexed                        │             failed
                         │                          ▼
                         │                      outdated
                         │
             ┌───────────┴──────────────────────────┐
             │  재인덱스/삭제 경로                      │
             │                                      │
             │  POST /reindex ──► pending ──► running │
             │                               │       │
             │                          인제스트 성공  │
             │                               ▼       │
             │                           indexed     │
             │                                       │
             │  DELETE /docs/{id} ──► pending ──► deleting
                                                 │
                          ┌──────────────────────┤
                          │                      │
                     soft delete            hard delete
                    (force=False)           (force=True)
                    Qdrant 청크 삭제          Qdrant 청크 삭제
                     hashband 삭제            hashband 삭제
                        S3 유지                 S3 삭제
                          │                      │
                          ▼                      ▼
                       deleted            (DB 레코드 삭제)
```

### 경로별 상세 전이

#### S3 업로드 경로

```
(신규 문서)
  API 수신 → DB 행 생성 → uploading
             → S3 업로드 완료 → pending + Redis 큐 push
             → 큐 워커 dequeue → running
             → 파이프라인 성공 → indexed
             → 파이프라인 실패 → failed

(기존 문서 재업로드 — stable 상태만)
  API 수신 → uploading (행 갱신)
             → (이후 동일)
```

#### dedup 판정

```
  running 중 dedup 실행:

  body_match=none               → needs_indexing=True  (정상 인덱싱)
  body_match=identical_level
    title_match=same            → incoming → outdated  (기존 doc 재사용)
    title_match=changed
      incoming 더 최신           → incoming → indexed, existing → outdated
      incoming 더 오래됨          → incoming → outdated
  body_match=similar
    incoming 더 최신             → existing 청크 삭제 후 needs_indexing=True
    incoming 더 오래됨           → incoming → outdated (청크 미생성)
```

#### 삭제 경로

```
  DELETE /docs/{id} (stable 상태만)
  → pending (enqueue_delete_event)
  → 큐 워커 dequeue → deleting

  indexed + force=False (soft delete)
  → Qdrant 청크 삭제 + hashband 삭제 → DB status='deleted' (S3 유지)

  indexed + force=True 또는 그 외 stable 상태 (hard delete)
  → Qdrant 청크 삭제 + hashband 삭제 + S3 삭제 → DB 행 삭제 (CASCADE)
```

---

## 3. API별 허용 조건

### POST /kb/{kb_id}/docs/upload — 단건 업로드

| 조건 | 결과 |
|------|------|
| 신규 문서 (동일 source_uri 없음) | 202 — DB 행 생성 후 업로드 시작 |
| 기존 문서 + 활성 상태 | 409 — Document is active |
| 기존 문서 + 안정 상태 | 202 — 재업로드 시작 |

### POST /kb/{kb_id}/docs/upload/batch — 배치 업로드

파일별로 단건 업로드와 동일한 조건을 적용한다. 개별 파일 실패는 다른 파일에 영향을 주지 않는다.

### DELETE /kb/{kb_id}/docs/{doc_id} — 문서 삭제

| 조건 | 결과 |
|------|------|
| 활성 상태 | 409 — Document is active |
| `deleted` 상태 | 202 — 이벤트 drop (실제 처리 없음, enqueue_delete_event 내부에서 차단) |
| 그 외 안정 상태 | 202 — 삭제 큐 push, `pending`으로 전환 |

### POST /kb/{kb_id}/docs/{doc_id}/reindex — 단건 재인덱스

| 조건 | 결과 |
|------|------|
| 활성 상태 | 409 — Document is active |
| `outdated` 상태 | 202 — 허용 (사용자 명시적 요청으로 간주) |
| `deleted` 상태 | 202 — 이벤트 drop (enqueue_upload_event 내부에서 차단) |
| ETag 일치 + force=False | `{queued: 0, skipped: 1}` — 변경 없음으로 skip |
| 그 외 | 202 — 인덱스 큐 push |

### POST /kb/{kb_id}/reindex — KB 전체 재인덱스

| 조건 | 동작 |
|------|------|
| 활성 상태 | skipped 카운트 증가 (에러 없음) |
| `outdated` 상태 | skipped 카운트 증가 (구버전 문서 제외) |
| `deleted` 상태 | 쿼리 단계에서 제외 (`include_deleted=False`) |
| ETag 일치 + force=False | skipped 카운트 증가 |
| 그 외 | queued 카운트 증가, 인덱스 큐 push |

응답 형식:
```json
HTTP 202 Accepted
{
  "kb_id": "<kb_id>",
  "queued": 3,
  "skipped": 2
}
```

### POST /kb/{kb_id}/docs/{doc_id}/fail — 강제 실패 전환

| 조건 | 결과 |
|------|------|
| `uploading` / `pending` / `running` / `deleting` | 200 — `failed`로 전환 |
| 그 외 상태 | 409 — Cannot force-fail |

수행 작업 (순서대로):
1. `run_id`가 있으면 Dagster run force-terminate
2. Redis 큐에서 이 문서의 upload 이벤트 제거 (`dequeue_upload_events`)
3. `status → failed` + last_error 필드 기록

> queue_worker 모드에서 `running` / `deleting` 상태인 경우, 백그라운드 태스크를 종료할 수 없어 상태만 `failed`로 전환된다. 태스크가 완료되면 상태를 덮어쓸 수 있다. 응답에 `warning` 필드가 포함된다.

### POST /kb/{kb_id}/docs/{doc_id}/recover — stuck 문서 복구

| 조건 | 결과 |
|------|------|
| `running` 상태 | 202 — `failed`로 전환 후 재인덱스 큐 push |
| 그 외 상태 | 409 — Not in a recoverable state |

---

## 4. 409 응답 형식

```json
HTTP 409 Conflict
{
  "detail": "Document is active, try again later: doc_id=<doc_id> status=<status>"
}
```

---

## 5. 큐 워커 지연(delay) 처리

큐 워커가 이벤트를 dequeue할 때 문서 상태를 확인하여 즉시 처리할 수 없는 경우 delay 큐로 이동한다.

| 이벤트 | 문서 상태 | 동작 |
|--------|----------|------|
| upload 이벤트 | `running` | delay 큐로 이동 (처리 중인 파이프라인 충돌 방지) |
| upload 이벤트 | `deleting` | delay 큐로 이동 (삭제 완료 후 재처리) |
| delete 이벤트 | `running` | delay 큐로 이동 (파이프라인이 파일을 읽는 도중 삭제 방지) |

---

## 6. 서버 재시작 시 상태 복구

서버(FastAPI)가 재시작되면 백그라운드 태스크가 종료되지만 Postgres의 `status`는 `running` / `uploading` / `deleting`으로 남을 수 있다.

이 상태에서:

- upload / delete / reindex API → 409 차단
- 수동 복구: `POST /fail` 호출로 `failed`로 전환 후 재처리

---

## 7. 구현 위치

| 구성 요소 | 위치 |
|-----------|------|
| 상태 전이 함수 (`set_pending`, `set_uploading`, ...) | `src/pipeline/utils/doc_state.py` |
| `_STABLE_STATUSES`, `is_active()` | `src/pipeline/utils/doc_state.py` |
| 차단 로직 (upload / delete / reindex) | `src/api/routers/docs.py` |
| force-fail / recover API | `src/api/routers/docs.py` |
| 큐 push / dequeue | `src/pipeline/queue/enqueue.py` |
| 큐 워커 (dequeue + delay) | `src/pipeline/queue/queue_worker.py` |
| dedup 판정 후 상태 전이 | `src/pipeline/step/dedup/verdict.py` |
| 삭제 파이프라인 | `src/pipeline/step/delete.py` |
| S3 업로드 경로 상태 전이 | `src/api/routers/docs.py` |
