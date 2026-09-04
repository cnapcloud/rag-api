# HTTP 에러 코드

`RAGError` 예외 계층(`.claude/rules/conventions/05-exception-handling.md`)이 어떤 HTTP status로
매핑되는지, 어떤 하위 인프라 예외가 어떤 status를 유발하는지 정리한다.

| Status | 예외 클래스 | 발생 조건 |
|--------|-------------|-----------|
| 403 | `HookAbort` | 등록된 파이프라인 훅 콜백이 신규 문서 유입을 의도적으로 중단 ([pipeline-hooks.md](pipeline-hooks.md)) |
| 403 / 422 | `BatchUploadError` | 배치 업로드가 실패 항목을 포함한 채 종료 (아래 참조) |
| 404 | `NotFoundError` | KB 또는 문서 없음 |
| 409 | `ConflictError` | 이미 존재하는 KB, 활성 상태 문서에 대한 중복 요청, 복구 불가 상태 |
| 422 | `IngestValidationError` | 파일 크기 초과, 지원하지 않는 형식 |
| 500 | `ConfigError` | 설정 오류 (vector_size 불일치 등) |
| 502 | `botocore.exceptions.ClientError` | S3 연결 실패 |
| 503 | `redis.RedisError` | Redis 연결 실패 |
| 503 | `psycopg.Error` | Postgres 연결 실패 |

`HookAbort` / `BatchUploadError` 는 `RAGError` 계층에 속하지 않는다(`Exception` 직속).

## 배치 업로드 (`POST /kb/{kb_id}/docs/upload/batch`)

배치는 파일을 **전부 순회(collect-and-continue)**하며 항목별 결과를 모은다.

- 각 파일: 성공 시 `{doc_id, source, etag, status_url}`, 개별 실패(지원하지 않는 형식, S3
  오류) 시 `{title, error, status: "error"}` 를 `results` 에 추가하고 다음 파일로 계속한다.
- `HookAbort`(quota 등): 이후 모든 파일이 같은 훅에 걸리므로, 실제 차단된 파일 1건을
  `{title, error, status}` 로 기록하고 남은 파일은 `{error: "Skipped: batch stopped at ..."}`
  로 채운 뒤 루프를 멈춘다. `results` 는 항상 제출한 파일과 1:1.

루프가 끝났을 때:

- **실패 항목 없음** → `202`, 본문 `{results: [...]}` (라우트 선언 기본값).
- **실패 항목 있음** → 라우터가 `BatchUploadError(results, detail=<첫 실제 실패 사유>,
  by_hook=<훅 중단 여부>)` 를 raise, `api/app.py` 핸들러가:
  - `by_hook=True` → `403` (단일 업로드와 동일)
  - `by_hook=False` → `422`
  - 본문 `{results: [...], detail: "<한 줄 사유>"}` — 성공 항목의 `doc_id`/`status_url` 과
    UI용 대표 메시지를 함께 보존.

이미 업로드된 파일은 반복마다 개별 커밋되므로 실패 응답에서도 유지된다.

409 응답 본문 형식과 활성 상태 판정 기준은 [doc-state-flow.md](doc-state-flow.md) 참조.
