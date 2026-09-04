# US-52: 배치 문서 업로드 실패 시 HTTP 상태 코드 정합성 + 실패 사유 노출

**상태**: done

> 설계: [pipeline-hooks.md](../../docs/internal/design/pipeline-hooks.md), [http-error-codes.md](../../docs/internal/design/http-error-codes.md)

## 목적

`POST /kb/{kb_id}/docs/upload/batch` 는 `HookAbort`(quota 초과 등)나 개별 파일 실패가 있어도
항상 `202` 를 반환했다. 상태 코드만 보는 소비자(로그/모니터링/스크립트)는 "전부 실패"도 성공으로
읽는다. 또한 hook 중단 시 걸린 파일 뒤의 **시도조차 안 한 파일들**까지 동일한 error 문자열로
채워, 각 파일이 개별적으로 quota에 걸린 것처럼 오해를 줬다.

rag-admin 업로드 모달은 `N of M file(s) uploaded successfully` 카운트만 보여주고 실패 사유는
어디에도 렌더하지 않았다. 카운트는 유지하되 그 아래에 사유 한 줄을 노출한다.

## 범위

### rag-api

- `upload_docs_batch` collect-and-continue: 파일을 전부 순회하며 `results` 에 항목별 결과 누적.
  - 성공: `{doc_id, source, etag, status_url}`.
  - `IngestValidationError`(형식) / `ClientError`(S3): 그 파일만 `{title, error, status:"error"}`
    기록하고 계속.
  - `HookAbort`: 차단된 파일 1건 error 기록 + 남은 파일 `{error:"Skipped: batch stopped at ..."}`
    로 채우고 `break`. `results` 는 제출 파일과 항상 1:1.
- 루프 후 실패 항목이 있으면 `BatchUploadError(results, detail, by_hook)` raise (신규 예외,
  `rag_api/exceptions.py`, `HookAbort` 처럼 RAGError 아님). `detail` = 첫 실제 실패 사유 원문.
- `api/app.py` 핸들러: `by_hook` → `403`(훅, 단일 업로드와 동일) / 그 외 → `422`,
  본문 `{results: [...], detail: "<한 줄 사유>"}`. status 결정은 `05-exception-handling.md`
  규칙대로 `app.py` 에만.
- 전부 성공 → `202` + `{results: [...]}` (기존 유지).
- 설계 문서: `pipeline-hooks.md`(§2.7 + 포획 표), `http-error-codes.md`(배치 규약, 기존
  "200 + 항목별 error" 오기 수정), `frontend.md`(응답 shape).
- 테스트: `tests/unit/test_docs_upload_hooks.py::TestUploadBatchHook`.

### rag-ent-api

- 자체 배치 엔드포인트 없음(vendored `docs` 라우터). `_register_exception_handlers` 가 rag-api를
  미러링하므로 `BatchUploadError` 핸들러(`{results, detail}`, 403/422)를 동일하게 추가.
- `HookAbort` 핸들러 주석 / `IngestQuotaError` docstring 를 collect + `BatchUploadError` 서술로
  갱신 (이전 커밋 `f4fd3d40` 의 fail-fast 문구 정리).

### rag-admin

- `src/types` `BatchUploadOutcome { results, detail }` 추가.
- `src/api/docs.ts` `uploadBatch` 반환형 `Promise<BatchUploadOutcome>`:
  - 2xx → `{ results, detail: null }`
  - non-2xx인데 본문에 `results` 배열 있음(403/422) → `resolve({ results, detail })` (예외 아님)
  - 413 / 본문에 `results` 없는 오류 → 기존대로 `reject`
- `src/components/document/UploadModal.tsx`:
  - `ErrorLine` 컴포넌트 추출: `truncate` 한 줄 + 말줄임, `scrollWidth > clientWidth` 로 실제
    넘칠 때만 Radix `Tooltip` 으로 전체 노출.
  - `phase="done"` 렌더: 요약줄 **항상 중립색**(`text-foreground`), 아이콘만 상태 표시
    (`CheckCircle2` / `AlertCircle`). `errorMsg`(=`detail`) 있으면 그 아래 `ErrorLine`.
  - `phase="error"`(네트워크/413/본문없는 오류): `ErrorLine`.

## 비범위

- **fail-fast(첫 실패 즉시 중단)**: 세션 중 한 차례 채택했다가 되돌림 — 프론트에서 `N of M`
  카운트를 보여주려면 항목별 결과 배열이 필요해 collect-and-continue로 최종 확정.
- **207 Multi-Status**: 클라이언트 처리 부담. 202/4xx 이분 + 본문 상세로 충분.
- **중단 이전 성공분 롤백**: 반복마다 커밋된 문서는 그대로 큐 처리. 4xx여도 본문 `results` 로
  추적 가능.
- **단일 업로드(`upload_doc`)**: 이미 `HookAbort` → 403. 변경 없음.
- **CLI ingest**: 배치 엔드포인트를 타지 않음.

## 완료 기준

- [x] 전부 성공 → `202` + `{results:[{doc_id,...}]}`, 본문에 `detail` 없음
- [x] 훅 중단 → `403` + `{results, detail}`, `results` 는 제출 파일과 1:1 (차단 1건 + 나머지 skipped)
- [x] 형식/S3 개별 실패 → `422` + `{results, detail}`, 배치는 끝까지 처리 (`results` 길이 == 파일 수)
- [x] `test_docs_upload_hooks.py::TestUploadBatchHook` 재작성 — 403/422/202 + `results` 1:1 + `detail`
- [x] `pipeline-hooks.md` / `http-error-codes.md` / `frontend.md` 갱신
- [x] rag-api 유닛 테스트 전체 통과 (653 passed)
- [x] rag-ent-api — `BatchUploadError` 핸들러 미러링 + 주석/docstring 갱신, `test_app.py` / `test_doc_quota.py` (50) 통과
- [x] rag-admin `uploadBatch` → `{results, detail}`, `UploadModal` 카운트(중립) + `ErrorLine`(빨강 한 줄 + 넘치면 툴팁). `tsc -b` / `eslint` 통과

## 진행 메모

- 2026-09-04: 배치 실패 처리 방향이 세션 중 여러 번 바뀜 —
  collect+`BatchUploadError`(초기) → fail-fast(커밋 `a75d8a3`, main 머지) →
  **collect-and-continue + `BatchUploadError(results, detail, by_hook)` + `{results, detail}` 본문**(최종).
  rag-admin 모달은 `N of M` 카운트(중립색) + 그 아래 `detail` 빨간 한 줄로 확정.
- 최종 커밋 세트: rag-api(collect + `BatchUploadError(results, detail, by_hook)`), rag-ent-api
  (핸들러 미러링), rag-admin(`{results, detail}` + `ErrorLine`). 이전 fail-fast 커밋
  (rag-api `a75d8a3` main 머지됨, rag-ent-api `f4fd3d40`) 위에 방향을 되돌리는 커밋.

## 의존성

- US-51 — 파이프라인 훅(`BeforeDocCreate`/`HookAbort`/`emit`). done.
