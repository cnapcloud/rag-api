# HTTP 에러 코드

`RAGError` 예외 계층(`.claude/rules/conventions/05-exception-handling.md`)이 어떤 HTTP status로
매핑되는지, 어떤 하위 인프라 예외가 어떤 status를 유발하는지 정리한다.

| Status | 예외 클래스 | 발생 조건 |
|--------|-------------|-----------|
| 403 | `HookAbort` | 등록된 파이프라인 훅 콜백이 신규 문서 유입을 의도적으로 중단 ([pipeline-hooks.md](pipeline-hooks.md)) |
| 404 | `NotFoundError` | KB 또는 문서 없음 |
| 409 | `ConflictError` | 이미 존재하는 KB, 활성 상태 문서에 대한 중복 요청, 복구 불가 상태 |
| 422 | `IngestValidationError` | 파일 크기 초과, 지원하지 않는 형식 |
| 500 | `ConfigError` | 설정 오류 (vector_size 불일치 등) |
| 502 | `botocore.exceptions.ClientError` | S3 연결 실패 |
| 503 | `redis.RedisError` | Redis 연결 실패 |
| 503 | `psycopg.Error` | Postgres 연결 실패 |

`HookAbort`는 `RAGError` 계층에 속하지 않는다(`Exception` 직속).

## 배치 업로드 (`POST /kb/{kb_id}/docs/upload/batch`)

배치는 파일을 순서대로 처리하다가 **첫 실패에서 즉시 중단(fail-fast)**한다. 별도 배치 전용
예외는 없고, 라우터는 배치 컨텍스트(파일명, 잔여 수)를 로그로 남긴 뒤 그 예외를 그대로
전파해 위 전역 매핑을 타게 한다.

- **전부 성공** → `202`, 본문 `{results: [...]}` (라우트 선언 기본값). 각 항목은
  `{doc_id, source, etag, status_url}`.
- **훅 중단** (`HookAbort`, quota 등) → 전파 → `403`, 본문 `{detail: "<사유>"}`
  (단일 업로드 경로와 동일).
- **지원하지 않는 형식** (`IngestValidationError`) → `422`, 본문 `{detail: ...}`.
- **S3 오류** (`ClientError`) → `502`.

중단 시점 이전에 이미 업로드된 파일은 row 생성 + 큐 적재가 반복마다 개별 커밋되므로 그대로
유지된다(응답에는 성공 목록이 실리지 않음 — 문서 목록 조회로 확인). 중단된 파일 이후의 파일은
시도되지 않는다.

409 응답 본문 형식과 활성 상태 판정 기준은 [doc-state-flow.md](doc-state-flow.md) 참조.
