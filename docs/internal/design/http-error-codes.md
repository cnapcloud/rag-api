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

`HookAbort`는 `RAGError` 계층에 속하지 않는다(`Exception` 직속). `upload_docs_batch`처럼 훅
중단을 경로별로 자체 처리하는 곳은 이 전역 매핑을 타지 않고 200 + 항목별 error로 응답한다.

409 응답 본문 형식과 활성 상태 판정 기준은 [doc-state-flow.md](doc-state-flow.md) 참조.
