# US-56: GitHub/Web 커넥터 title 결정 방식 변경 — 설계

> 담당: `designer` · spec 워크플로우 2단계 · 템플릿: `.claude/templates/design.md`

**대상**: [spec.md](spec.md)

## 아키텍처 개요

- 컴포넌트 흐름: (변경 없음) `GitHubConnector`/`WebConnector` (Pipeline 레이어, `src/rag_api/connectors/`)
  → `infra.postgres.create_doc`/`set_staged` — title은 커넥터가 문서 생성/스테이징 시
  넘기는 순수 값이므로 이번 변경은 Pipeline 레이어 내부에서만 끝난다.
- 변경 모듈:
  - `src/rag_api/connectors/github.py` (수정) — `title=path` → `title=Path(path).name`
  - `src/rag_api/connectors/web.py` (수정) — `_extract_title`에서 `article h1`/`h1`
    셀렉터 제거, fallback을 URL 마지막 path 세그먼트로 바꾸기 위한 헬퍼
    `_url_last_segment` 신규 추가
  - `src/rag_api/connectors/confluence.py` — 변경 없음 (F3 회귀 방지 대상, 코드
    미수정 확인용으로만 언급)
- 관련 설계 문서: (없음 — 커넥터별 title 산출은 별도 design 문서로 관리되지 않음)

## 영향 레이어 / 파일

| 레이어 | 파일 | 변경 내용 |
|---|---|---|
| Pipeline (connectors) | `src/rag_api/connectors/github.py` | 217번 라인(`create_doc(title=path, ...)`)과 255번 라인(`set_staged(doc_id, title=path, ...)`)의 `title=path`를 `title=Path(path).name`으로 변경. `source=source_uri`(217번 라인 위)는 그대로 유지 — F1-4 대응. `Path`는 이미 import되어 있음(1-8번 라인) |
| Pipeline (connectors) | `src/rag_api/connectors/web.py` | `_extract_title`(76-107번 라인) 내부의 `article h1` 블록(89-93번 라인)과 `h1` 블록(95-99번 라인) 삭제. 신규 함수 `_url_last_segment(url: str) -> str` 추가(같은 파일, `_extract_title` 위). 호출부 364번 라인 `_extract_title(html, source_uri)`와 394번 라인 `_extract_title(html, source_uri)`를 `_extract_title(html, _url_last_segment(source_uri))`로 변경. 384번 라인(`create_doc(title=source_uri, ...)`)은 생성 직후 393-394번에서 곧바로 `_extract_title` 결과로 `set_staged`가 덮어쓰므로 최종 title에 영향 없음 — 변경하지 않음(스코프 최소화) |
| Pipeline (connectors) | `src/rag_api/connectors/confluence.py` | 변경 없음 (F3-1/F3-2 회귀 확인 대상) |

역방향 참조 확인: 두 파일 모두 Pipeline 레이어 내부 수정이며 `Path`/`urlparse` 등
표준 라이브러리 사용만 추가된다. API/Infra 레이어를 참조하는 방향은 기존과 동일하게
유지되고(예: `infra.postgres`, `infra.s3` 호출), 하위 레이어(Infra)가 Pipeline을
역참조하는 변경은 없다.

## 신규 의존성 (해당 시)

(없음) — `Path`(pathlib), `urlparse`(urllib.parse) 모두 표준 라이브러리이며 두 파일에
이미 import되어 있음.

## API 계약 (해당 시)

(해당 없음) — 커넥터 내부 title 산출 로직 변경으로, API 요청/응답 계약에는 영향 없음.

## 데이터 모델 (해당 시)

문서(`docs` 테이블)의 `title` 필드 값 산출 방식만 바뀐다. 스키마 변경 없음.
`source`(source_uri) 필드는 GitHub의 경우 F1-4에 따라 기존과 동일하게 전체 경로를
유지한다.

## 에러 모델 (해당 시)

(해당 없음) — 예외 처리 경로 변경 없음. `_url_last_segment`는 항상 문자열을
반환하도록 설계해(아래 구현 방법 참조) 새로운 예외를 발생시키지 않는다.

## 로깅 (해당 시)

(해당 없음) — 기존 로그 문(`logger.info("GitHub file staged: ... path=%r", ...)`,
`logger.info("Web page staged: ... title=%r", ...)`)은 그대로 유지되며 값만 바뀐
title/path를 그대로 실어 나른다. 로그 포맷 자체는 변경하지 않는다.

## NFR (해당 시)

(해당 없음) — spec.md에 NFR 항목 없음.

## 리스크 & 롤백

- 리스크: `web.py`의 `_extract_title` 기존 단위테스트 중 `article h1`/`h1` 우선순위를
  검증하는 테스트(`test_article_h1_wins_over_h1`, `test_h1_wins_over_h1`,
  `test_empty_h1_falls_through_to_title`)가 새 동작과 맞지 않아 실패한다 — 회귀가
  아니라 사양 변경에 따른 예상된 실패이므로, 해당 테스트를 새 우선순위(og:title ->
  `<title>` -> fallback)에 맞게 수정/삭제해야 한다. 완화책: task.md에서 테스트 수정
  범위를 명시하고, 변경 후 `tests/unit/test_web_connector.py` 전체 재실행으로 확인한다.
- 리스크: GitHub 파일명 충돌(다른 디렉터리, 동일 파일명) 시 title만으로는 구분이 안 될
  수 있음 — spec.md 비범위에 명시된 대로 이번 범위에서 다루지 않음(완화책 불필요,
  향후 별도 US).
- 리스크: `_url_last_segment`가 빈 문자열을 반환하는 극단적 URL(예: 스킴만 있는 URL)이
  있으면 F2-4 의도(빈 문자열 금지)가 깨질 수 있음. 완화책: path 세그먼트가 모두
  비어있으면 `netloc`으로, `netloc`도 비어있으면 원본 URL 문자열로 폴백하는 다단계
  fallback으로 구현한다(아래 task.md T2 구현 방법 참조).
- 롤백: 두 파일 모두 순수 로직 변경(스키마/마이그레이션 없음)이므로 커밋 revert만으로
  충분하다.

## 오픈 이슈 (선택)

(없음)

## 설계 검토 체크

- [x] `architecture` 스킬 기준 레이어/의존성 방향 확인 완료 (역방향 참조 없음)
- [x] spec.md의 모든 완료 기준(AC)이 이 설계로 커버됨
- [x] 오픈 이슈 없음
