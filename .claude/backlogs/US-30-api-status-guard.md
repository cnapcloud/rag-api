# US-30 — API Status Guard

## 요약

upload / delete / reindex API에서 문서가 활성 처리 중일 때 요청을 차단하는 상태 기반 가드를 구현한다.

## 배경

현재 `delete_doc`은 `running` 상태만 차단하고, `reindex_doc` / `reindex_kb` / `upload_doc`은 status 체크가 전혀 없다.
활성 상태(`pending`, `uploading`, `fetching`, `running`, `deleting`) 문서에 요청이 들어오면 파이프라인 충돌, 큐 이벤트 중복, 상태 불일치 등이 발생할 수 있다.

설계 문서: `docs/internal/design/doc-status-guard.md`

## 구현 항목

- SG-01: `doc_state.py` — `_STABLE_STATUSES` + `is_active()` 추가
- SG-02: `delete_doc` — `is_active()` 차단 확장 + warning 로깅
- SG-02a: `enqueue_delete_event` — `deleted` 상태 drop 가드 추가
- SG-03: `reindex_doc` — `is_active()` 차단 + warning 로깅
- SG-04: `reindex_kb` — 활성 상태 skip + `outdated` 제외 + 로깅
- SG-05: `upload_doc` / `upload_docs_batch` — 기존 doc 재업로드 시 `is_active()` 차단 + 로깅

## 인수 조건

- 활성 상태 doc에 upload / delete / reindex 요청 시 HTTP 409 반환
- `reindex_kb`는 활성 / outdated doc을 skipped 카운트로 건너뜀
- `enqueue_delete_event`가 `deleted` doc 이벤트를 drop함 (`enqueue_upload_event`와 대칭)
- 모든 차단 케이스에 warning 로그 기록
