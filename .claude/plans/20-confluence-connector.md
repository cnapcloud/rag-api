# Plan 20 — ConfluenceConnector implementation (R-10)

**Covers**: US-20  
**Status**: in-progress

---

## 목표

Confluence REST API v1을 이용해 스페이스의 페이지와 첨부파일을 수집하고,
Flow B(fetch → stage → enqueue)를 수행하는 `ConfluenceConnector` 구현.

---

## 영향 범위

| 파일 | 변경 |
|------|------|
| `pyproject.toml` | 변경 없음 (html2text 불필요) |
| `src/connectors/confluence.py` | 신규 |
| `src/api/routers/connectors.py` | `_dispatch_sync`에 confluence 분기 추가 |
| `tests/unit/test_confluence_connector.py` | 신규 |
| `.claude/backlogs/backlog.md` | US-20 행 추가 |
| `.claude/plans/plan.md` | plan 20 행 추가 |

---

## 설계 결정

### 1. API 엔드포인트 (Confluence REST API v1)

| 목적 | 엔드포인트 |
|------|-----------|
| 페이지 목록 | `GET /rest/api/content?spaceKey=&type=page&expand=version,metadata.labels,body.view` |
| 첨부파일 목록 | `GET /rest/api/content/{page_id}/child/attachment?expand=version` |
| 첨부파일 다운로드 | `_links.download` (상대 경로) |

Cloud(`*.atlassian.net`): API base = `{base_url}/wiki/rest/api`  
Server: API base = `{base_url}/rest/api`

### 2. 인증

| 토큰 형식 | 인증 방식 |
|-----------|---------|
| `email:api_token` (`:` 포함) | `Authorization: Basic base64(email:token)` |
| PAT 문자열 | `Authorization: Bearer {token}` |
| 없음 (공개 사이트) | 헤더 없음 |

### 3. content_version

- 페이지: `str(page["version"]["number"])`
- 첨부파일: `str(attachment["version"]["number"])`
- 동일하면 재인제스트 생략 (첨부파일은 여전히 순회)

### 4. 첨부파일 필터링

```
extension in SUPPORTED_EXTENSIONS  (parse.py 기준)
AND fileSize < max_attachment_bytes  (default: 10MB)
```

`SUPPORTED_EXTENSIONS = {".pdf", ".md", ".docx", ".txt", ".hwp", ".html", ".htm", ".rst"}`

### 5. source_uri

| 대상 | 형식 | 정규화 |
|------|------|--------|
| 페이지 | `confluence://{space_key}/{page_id}` | `normalize_source_uri("confluence", ...)` → lowercase space_key |
| 첨부파일 | `confluence://{space_key}/attachments/{att_id}` | space_key.lower() 직접 적용 |

### 6. 페이지가 변경 없을 때도 첨부파일 순회

페이지 버전이 동일해도 첨부파일은 새로 추가/변경될 수 있으므로 항상 순회.

### 7. 레이블 제외

`exclude_labels` 에 해당하는 페이지는 본문 및 첨부파일 모두 건너뜀.

### 8. 오류 처리

- 페이지 S3 스테이징 실패 → 해당 페이지 doc `status=failed`, 계속 (첨부파일도 진행)
- 첨부파일 다운로드/스테이징 실패 → 해당 첨부파일 doc `status=failed`, 다음으로 계속
- 첨부파일 목록 API 실패 → 로그 error, 해당 페이지 첨부파일 생략 후 계속

---

## 구현 단계

1. [x] backlog US-20 작성
2. [x] plan 파일 작성
3. [x] `pyproject.toml` — html2text 불필요 (doc_type=html로 변경)
4. [ ] `src/connectors/confluence.py` 구현
   - `ConfluenceConnector.__init__()` — config 검증, auth 헤더 구성
   - `_api_base` property — Cloud/Server 자동 감지
   - `_make_download_url()` — 상대 경로 → 절대 URL
   - `sync()` — 페이지 순회 진입점
   - `_iter_pages()` — 페이지네이션
   - `_has_excluded_label()` — 레이블 필터
   - `_process_page()` — Flow B 페이지 처리
   - `_iter_attachments()` — 첨부파일 페이지네이션
   - `_process_page_attachments()` — 첨부파일 순회 래퍼 (오류 격리)
   - `_process_attachment()` — Flow B 첨부파일 처리
5. [ ] `connectors.py` `_dispatch_sync` confluence 분기 추가
6. [ ] `test_confluence_connector.py` 단위 테스트
7. [ ] 테스트 실행 통과 확인
