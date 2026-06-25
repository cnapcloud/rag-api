# US-21 — GitHubConnector implementation (R-11)

## Summary

GitHub 레포지토리에서 소스코드 파일을 수집하여 파이프라인으로 인제스트하는 커넥터 구현.
소스코드 확장자 파싱 지원 및 CodeSplitter 자동 라우팅 포함.

## Acceptance Criteria

1. `GitHubConnector(config).sync(kb_id, connector_id)` 호출 시 Flow B 실행
2. GitHub REST API로 레포지토리 파일 트리 조회 (recursive tree)
3. `SUPPORTED_EXTENSIONS`(CODE_EXTENSIONS 포함) 내 확장자만 스테이징 — Confluence 패턴 동일
4. `content_version` = 파일 SHA — 변경 없으면 재인제스트 생략
5. parse_op: CODE_EXTENSIONS 확장자는 FlatReader로 처리
6. chunk_op: doc_type이 CODE_EXTENSIONS이면 CodeSplitter 자동 사용 (언어별 매핑)
7. `_dispatch_sync("github", ...)` 라우터에 연결
8. 단위 테스트 통과 (mock postgres, mock S3, mock httpx)

## Config Schema

```json
{
  "owner": "my-org",
  "repo": "my-repo",
  "branch": "main",
  "path_prefix": "src/",
  "auth_token_secret": "GITHUB_TOKEN",
  "request_delay_ms": 100,
  "request_timeout_sec": 30
}
```

## Source URI Format

`github://{owner}/{repo}/{branch}/{file_path}`

## Dependencies

- US-16 (Connector CRUD + Sync API) — done
- US-15 (Pipeline doc_id-based) — done
- US-17 (HTML clean reader / parse_op) — done
