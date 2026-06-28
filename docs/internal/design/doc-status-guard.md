# 문서 상태 기반 API 차단 정책

## 1. 개요

upload, delete, reindex API는 문서가 활성 처리 중일 때 요청을 수락하면 파이프라인 충돌, 큐 이벤트 중복, 상태 불일치 등의 문제가 발생한다.
이를 방지하기 위해 세 API 모두 동일한 "활성 상태" 기준으로 API 레이어에서 요청을 차단한다.

---

## 2. 문서 상태 분류

| 상태 | 의미 | 분류 |
|---|---|---|
| `pending` | 큐에 대기 중 | 활성 |
| `uploading` | S3 파일 전송 중 | 활성 |
| `fetching` | 커넥터가 컨텐츠 수집 중 (connector 전용) | 활성 |
| `running` | 인제스트 파이프라인 실행 중 | 활성 |
| `deleting` | 삭제 파이프라인 실행 중 | 활성 |
| `indexed` | 인덱싱 완료 | 안정 |
| `failed` | 파이프라인 실패 | 안정 |
| `deleted` | soft-delete 완료 | 안정 |
| `outdated` | dedup에 의해 구버전으로 판정됨 | 안정 |

활성 여부는 안정 상태의 여집합으로 정의한다. 새 상태가 추가될 경우 자동으로 활성으로 취급되어 안전한 기본값이 보장된다.

```python
_STABLE_STATUSES = frozenset({"indexed", "failed", "deleted", "outdated"})

def is_active(status: str) -> bool:
    return status not in _STABLE_STATUSES
```

---

## 3. API별 차단 정책

### 3.1 upload (`POST /kb/{kb_id}/docs/upload`)

- **신규 doc** (동일 source_uri 없음): 상태 체크 없이 통과
- **기존 doc** (동일 source_uri 존재): 활성 상태이면 `ConflictError` (HTTP 409)

차단 이유:
- `uploading`: 동시 업로드 경쟁 조건
- `pending` / `running`: S3 파일 교체 시 기존 큐 이벤트와 새 이벤트가 동일 doc을 중복 처리
- `fetching`: 커넥터가 컨텐츠를 수집하는 도중 파일 교체 시 상태 불일치
- `deleting`: 삭제 중인 문서에 새 파일 업로드 시 상태 불일치

### 3.2 delete (`DELETE /kb/{kb_id}/docs/{doc_id}`)

활성 상태이면 `ConflictError` (HTTP 409).

차단 이유:
- `running` / `fetching`: 파이프라인이 파일을 읽는 도중 삭제 시 파이프라인 오류
- `deleting`: 이미 삭제 진행 중 — 중복 삭제 이벤트 방지
- `uploading` / `pending`: 진행 중인 업로드/큐 이벤트가 완료된 뒤 삭제해야 일관성 유지

`deleted` 문서에 대한 delete 요청은 API 레이어가 아닌 `enqueue_delete_event`에서 차단한다. 이벤트를 drop하고 상태를 변경하지 않는다. API는 202를 반환하지만 실제 처리는 없다.

### 3.3 reindex (단건: `POST /kb/{kb_id}/docs/{doc_id}/reindex`)

활성 상태이면 `ConflictError` (HTTP 409).

차단 이유: 파이프라인이 이미 실행 중이거나 큐에 대기 중인 상황에서 추가 인덱싱 요청은 중복 처리를 유발한다.

`outdated` 상태는 차단하지 않는다. 사용자가 명시적으로 지정한 요청이므로 의도적인 재인덱싱으로 허용한다.

`deleted` 상태는 API 레이어에서 차단하지 않지만, `enqueue_upload_event`가 `deleted` doc의 이벤트를 drop하므로 실제로는 처리되지 않는다.

### 3.4 reindex (KB 전체: `POST /kb/{kb_id}/reindex`)

활성 상태인 doc은 에러 대신 `skipped` 카운트로 조용히 건너뛴다.
bulk 요청 특성상 일부 실패로 전체를 중단하지 않는다.

`deleted` 문서는 `pg_list_docs(include_deleted=False)` 쿼리 단계에서 이미 제외된다.
`outdated` 문서는 별도로 필터해야 한다 — 구버전으로 판정된 문서를 KB 전체 재인덱싱 대상에서 제외한다.

---

## 4. 차단 대상 및 응답

활성 상태(`is_active()` 반환 true)인 경우에만 차단한다. 안정 상태(`indexed`, `failed`, `deleted`, `outdated`)는 모든 API에서 통과한다.

| 상태 | upload (기존 doc) | delete | reindex (단건) | reindex (KB 전체) |
|---|---|---|---|---|
| `pending` | 409 | 409 | 409 | skipped |
| `uploading` | 409 | 409 | 409 | skipped |
| `running` | 409 | 409 | 409 | skipped |
| `deleting` | 409 | 409 | 409 | skipped |

### 409 응답 형식 (upload / delete / reindex 단건)

```json
HTTP 409 Conflict
{
  "detail": "Document is active, try again later: doc_id=<doc_id> status=<status>"
}
```

### skipped 응답 형식 (reindex KB 전체)

활성 상태 doc은 에러 없이 `skipped` 카운트에 포함된다.

```json
HTTP 202 Accepted
{
  "kb_id": "<kb_id>",
  "queued": 3,
  "skipped": 2
}
```

---

## 5. 로깅 정책

차단 이벤트는 `api/routers/docs.py`에서 `ConflictError`를 raise하기 직전에 남긴다.

| 케이스 | 레벨 | 메시지 패턴 |
|---|---|---|
| upload 차단 | `warning` | `Upload blocked — doc active: kb=%s doc_id=%s status=%s` |
| delete 차단 | `warning` | `Delete blocked — doc active: kb=%s doc_id=%s status=%s` |
| reindex 단건 차단 | `warning` | `Reindex blocked — doc active: kb=%s doc_id=%s status=%s` |
| reindex KB — 활성 상태 skip | `debug` | `Reindex skipped — doc active: doc_id=%s status=%s` |
| reindex KB — outdated skip | `debug` | `Reindex skipped — doc outdated: doc_id=%s` |
| reindex KB — 완료 summary | `info` | `Reindex KB: kb=%s queued=%d skipped=%d force=%s` (기존 유지) |

`warning`을 사용하는 이유: 클라이언트 요청 오류이지만 race condition에 의한 정상적인 충돌일 수 있어 `error`보다 낮은 수준이 적합하다.
reindex KB의 개별 skip은 summary에서 집계되므로 `debug`로 충분하다.

---

## 6. 구현 위치

| 구성 요소 | 위치 | 역할 |
|---|---|---|
| `_STABLE_STATUSES`, `is_active()` | `src/pipeline/utils/doc_state.py` | 활성 상태 판별 |
| 차단 로직 / 로깅 | `src/api/routers/docs.py` | 각 엔드포인트에서 `is_active()` 확인 후 `ConflictError` |

HTTP 상태 코드 매핑은 기존 규칙대로 `api/app.py`의 전역 핸들러에서 처리한다 (`ConflictError` → 409).

---

## 7. UI 처리 정책 (rag-admin)

### 7.1 선택 목록에 활성 상태 doc이 포함된 경우 (proactive)

reindex / delete 액션 버튼 클릭 시, 선택된 목록 중 활성 상태(`is_active()` 기준)인 doc이 하나라도 있으면 API를 호출하지 않고 즉시 토스트를 표시한다.

```
작업 중인 문서가 포함되어 있어 처리할 수 없습니다.
```

### 7.2 API 응답이 409인 경우 (reactive)

proactive 체크를 통과했더라도, 선택과 요청 사이의 race condition으로 409가 반환될 수 있다.
이 경우 다음 토스트를 표시한다.

```
일부 문서가 처리 중이어서 작업이 실패했습니다.
```

### 7.3 근거

UI의 doc status는 polling 스냅샷이므로 클릭 시점에 이미 낡았을 수 있다.
proactive 체크는 UX 보조이고, backend 409 차단이 실제 가드다.
두 레이어를 모두 구현해 정상 경로에서는 불필요한 API 호출을 줄이고, race condition에서는 명확한 피드백을 제공한다.

### 7.4 fetching 상태 처리

`fetching`은 connector 전용 상태로, rag-admin의 `DocStatus` 타입에 포함하지 않는다.
`isDocActive()` 헬퍼는 stable set(`indexed`, `failed`, `outdated`, `deleted`)의 여집합으로 판별하므로,
`fetching`이 타입에 없어도 런타임에 올바르게 활성 상태로 분류된다.

---

## 8. 활성 상태에서 진행하려면

활성 상태 문서를 강제로 초기화해야 할 경우 force-fail API를 먼저 사용한다:

```
POST /kb/{kb_id}/docs/{doc_id}/fail
```

`failed` 상태로 전환된 이후 원하는 작업(upload / delete / reindex)을 진행한다.


## 9. 개발 항목

| 우선순위 | ID | 대상 | 내용 | 상태 |
|---|---|---|---|---|
| 1 | SG-01 | `doc_state.py` | `_STABLE_STATUSES` 내부 상수 + `is_active(status)` 함수 추가 | done |
| 2 | SG-02 | `delete_doc` | `is_active()` 차단 확장 + warning 로깅 | done |
| 2-1 | SG-02a | `enqueue_delete_event` | `deleted` 상태 doc 이벤트 drop 가드 추가 (enqueue_upload_event와 대칭) | done |
| 3 | SG-03 | `reindex_doc` | `is_active()` 차단 + warning 로깅 추가 | done |
| 4 | SG-04 | `reindex_kb` | 활성 상태 doc skip + `outdated` doc 제외 + debug 로깅 추가 | done |
| 5 | SG-05 | `upload_doc` / `upload_docs_batch` | 기존 doc 재업로드 시 `is_active()` 차단 + warning 로깅 추가 | done |
| 6 | SG-06 | `docs/index.tsx` | bulk reindex / delete 클릭 시 선택 목록에 활성 상태 doc 포함 여부 proactive 체크 → 토스트 | done |
| 7 | SG-07 | `docs/index.tsx`, `DocDetailPanel.tsx` | mutation error handler에서 409 감지 → 토스트 메시지 추가 | done |