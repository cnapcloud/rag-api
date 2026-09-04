# US-52: 배치 문서 업로드 실패 시 HTTP 상태 코드 정합성 + 실패 사유 노출

**상태**: done

> 설계: [pipeline-hooks.md](../../docs/internal/design/pipeline-hooks.md), [http-error-codes.md](../../docs/internal/design/http-error-codes.md)

## 목적

`POST /kb/{kb_id}/docs/upload/batch` 는 `HookAbort`(quota 초과 등)나 개별 파일 실패가 있어도
항상 `202` 를 반환한다. 상태 코드만 보는 소비자(로그/모니터링/스크립트)는 "전부 실패"도 성공으로
읽는다. 또한 hook 중단 시 걸린 파일 뒤의 **시도조차 안 한 파일들**까지 동일한 error 문자열로
채워 넣어, 각 파일이 개별적으로 quota에 걸린 것처럼 오해를 준다.

단일 업로드(`upload_doc`)는 `HookAbort` → 전역 핸들러 → `403` 으로 이미 올바르게 동작하므로,
배치도 첫 실패에서 그 예외를 그대로 전파(fail-fast)하도록 맞춘다.

## 범위

### rag-api

- `upload_docs_batch` 를 fail-fast로 전환: 파일을 순서대로 처리하다 첫 실패에서 중단하고 그
  예외를 그대로 전파한다.
  - `except HookAbort` / `except (IngestValidationError, ClientError)` 두 분기 모두 배치 컨텍스트
    경고 로그(`file`, `remaining`)만 남기고 `raise` — 전역 핸들러가 403 / 422 / 502로 매핑.
  - 남은 파일 전부를 error로 채우던 루프, `stopped_by_hook` 플래그, 루프 후 집계 raise를 제거.
- 상태 코드 규약: 전부 성공 → `202` + `{results: [...]}`. 훅 중단 → `403` + `{detail}`.
  지원하지 않는 형식 → `422`. S3 오류 → `502`. 모두 기존 전역 핸들러(`api/app.py`)가 매핑 —
  **새 예외 클래스 없음**(`05-exception-handling.md`: status 결정은 `app.py` 에만).
- 설계 문서 동기화: `pipeline-hooks.md`(포획 지점 + §2.7), `http-error-codes.md`(배치 규약,
  기존 "200 + 항목별 error" 오기 수정), `frontend.md`(배치 응답 shape).
- 테스트: `tests/unit/test_docs_upload_hooks.py::TestUploadBatchHook`.

### rag-ent-api

- 자체 배치 엔드포인트 없음(vendored rag-api 라우터). 기존 `@app.exception_handler(HookAbort)`
  가 배치 fail-fast도 그대로 처리하므로 **핸들러 추가 불필요**.
- 옛 배치 동작을 서술하는 주석/문서만 동기화: `src/rag_ent/exceptions.py`(`IngestQuotaError`
  docstring), `src/rag_ent/api/app.py`(`HookAbort` 핸들러 주석).

### rag-admin

- `src/api/docs.ts` `uploadBatch`: non-2xx(413 제외)에서 `JSON.parse(responseText).detail` 을
  reject 메시지로 사용(파싱 실패 시 `responseText` 또는 `HTTP <status>` 폴백). `download` 이
  쓰는 것과 동일 패턴.
- `src/components/document/UploadModal.tsx` error 표시: `truncate` 로 한 줄 + 말줄임(...),
  `scrollWidth > clientWidth` 로 실제 넘칠 때만 Radix `Tooltip` 으로 전체 메시지 노출.
- 항목별 렌더링·"N of M" 분모 보정은 하지 않음 — fail-fast라 응답에 성공 목록이 없음.

## 비범위

- **collect-and-continue 유지**: 한 파일 실패해도 나머지를 계속 처리하고 항목별 결과를 모으는
  방식은 프론트가 메시지만 표시하기로 하면서 불필요 → fail-fast 채택. (이전 설계안이었음)
- **배치 전용 예외(`BatchUploadError`) 도입**: collect 방식에서만 필요. fail-fast에서는 각
  예외가 전역 매핑을 그대로 타므로 불필요.
- **207 Multi-Status**: 클라이언트 처리 부담이 크고 fail-fast에서는 부분 결과 자체가 없음.
- **중단 이전 성공분 롤백**: 반복마다 커밋된 문서는 그대로 큐 처리. 응답엔 안 실리고 문서
  목록 조회로 확인.
- **단일 업로드(`upload_doc`) 경로**: 이미 `HookAbort` → 403. 변경 없음.
- **CLI ingest 경로**: 배치 엔드포인트를 타지 않음.

## 완료 기준

- [x] 배치 전부 성공 → `202` + `{results: [{doc_id, source, etag, status_url}]}`
- [x] 훅 중단(quota 등) → `403` + `{detail: "<사유>"}`, 뒤 파일은 시도 안 함
- [x] 지원하지 않는 형식 → `422` (fail-fast로 중단)
- [x] `test_docs_upload_hooks.py::TestUploadBatchHook` 재작성 — 403/422/202 + fail-fast 검증
- [x] `pipeline-hooks.md` / `http-error-codes.md` / `frontend.md` 갱신
- [x] rag-ent-api — `exceptions.py` / `api/app.py` 주석 동기화, `test_app.py` / `test_doc_quota.py` 통과
- [x] rag-api 유닛 테스트 전체 통과 (653 passed)
- [x] rag-admin `uploadBatch` — non-2xx에서 `detail` 문자열을 reject 메시지로 사용;
      `UploadModal` 에러 한 줄 + 말줄임 + 넘칠 때만 툴팁. `tsc -b` / `eslint` 통과

## 진행 메모

- 2026-09-04: 설계를 collect-and-continue(+`BatchUploadError` +`{results}` 본문 유지)에서
  **fail-fast**(첫 실패 예외 전파, 새 예외 없음, `{detail}` 본문)로 전환. 프론트가 실패 시
  메시지 문자열만 표시하기로 결정되면서 부분 결과 데이터가 불필요해졌기 때문. rag-api +
  rag-ent-api + rag-admin 모두 완료.

## 의존성

- US-51 — 파이프라인 훅(`BeforeDocCreate`/`HookAbort`/`emit`). done. 이 훅 기반 위에서
  배치 핸들러의 `HookAbort` 포획 동작을 바꾼다.
