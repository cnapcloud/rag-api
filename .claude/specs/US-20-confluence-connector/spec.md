# US-20 — ConfluenceConnector implementation (R-10)

## Summary

Confluence 스페이스에서 페이지와 첨부파일을 수집하여 파이프라인으로 인제스트하는 커넥터 구현.

## Acceptance Criteria

1. `ConfluenceConnector(config).sync(kb_id, connector_id)` 호출 시 Flow B 실행
2. 스페이스 내 모든 페이지를 Confluence REST API v1으로 페이지네이션하여 열거
3. `exclude_labels` 에 해당하는 레이블을 가진 페이지(및 해당 페이지의 첨부파일)는 건너뜀
4. 페이지 본문은 `body.view` HTML을 그대로 `.html`로 스테이징 (HTMLCleanReader가 처리)
5. 각 페이지의 첨부파일 중 `SUPPORTED_EXTENSIONS` 내 포맷이고 크기가 `max_attachment_bytes` 미만인 것만 스테이징
   - 기본값: 10MB (`max_attachment_mb` config 미설정 시)
   - 첨부파일 source_uri: `confluence://{space_key}/attachments/{attachment_id}`
6. `content_version` = Confluence 버전 번호(`str(version.number)`) — 변경 없으면 재인제스트 생략
7. Cloud/Server 자동 감지: `.atlassian.net` 도메인이면 `/wiki/rest/api` 사용, 아니면 `/rest/api`
8. `auth_token_secret` 옵션: Cloud는 `email:api_token`(Basic auth), Server는 PAT(Bearer auth)
9. `_dispatch_sync("confluence", ...)` 라우터에 연결
10. 단위 테스트 통과 (mock postgres, mock S3, mock httpx)

## Source URI Formats

| 대상 | source_uri |
|------|-----------|
| 페이지 | `confluence://{lowercase_space_key}/{page_id}` |
| 첨부파일 | `confluence://{lowercase_space_key}/attachments/{attachment_id}` |

## Config Schema

```json
{
  "base_url": "https://company.atlassian.net",
  "space_key": "DEV",
  "auth_token_secret": "CONFLUENCE_TOKEN",
  "exclude_labels": ["draft", "archived"],
  "max_attachment_mb": 10,
  "request_delay_ms": 100,
  "request_timeout_sec": 30
}
```

## Dependencies

- R-07 (Connector sync API, `_dispatch_sync`) — done (US-16)
- R-04 (Pipeline doc_id-based) — done (US-15)
- 추가 의존성 없음 (HTMLCleanReader 재사용)
