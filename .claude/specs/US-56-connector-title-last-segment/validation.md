# US-56: GitHub/Web 커넥터 title 결정 방식 변경 — 검증 결과

> 담당: `validator` · spec 워크플로우 4단계(최종) · 템플릿: `.claude/templates/validation.md`

**대상**: [spec.md](spec.md) / [design.md](design.md) / [task.md](task.md)

## 완료 기준 검증

| AC | Task | 검증 방법 | 결과 | 비고 |
|---|---|---|---|---|
| F1-1 | T1 | `uv run pytest -q tests/unit/test_github_connector.py` | PASS | (재사용: implementation.md) — 20 passed |
| F1-2 | T1 | `uv run pytest -q tests/unit/test_github_connector.py` | PASS | (재사용: implementation.md) |
| F1-3 | T1 | `uv run pytest -q tests/unit/test_github_connector.py` | PASS | (재사용: implementation.md) |
| F1-4 | T1 | `uv run pytest -q tests/unit/test_github_connector.py` | PASS | (재사용: implementation.md) |
| F2-1 | T2 | `uv run pytest -q tests/unit/test_web_connector.py` | PASS | (재사용: implementation.md) — 69 passed |
| F2-2 | T2 | `uv run pytest -q tests/unit/test_web_connector.py` | PASS | (재사용: implementation.md) |
| F2-3 | T2 | `uv run pytest -q tests/unit/test_web_connector.py` | PASS | (재사용: implementation.md) — `test_url_last_segment*` 확인 |
| F2-4 | T2 | `uv run pytest -q tests/unit/test_web_connector.py` | PASS | (재사용: implementation.md) — trailing slash/netloc fallback 테스트로 빈 문자열 아님 확인 |
| F3-1 | T3 | `uv run pytest -q tests/unit/test_confluence_connector.py` | PASS | (재사용: implementation.md) — `page["title"]` 직접 사용 확인 |
| F3-2 | T3 | `uv run pytest -q tests/unit/test_confluence_connector.py` | PASS | (재사용: implementation.md) — 기존 테스트 수정 없이 통과 |
| C1 | T3 | `uv run pytest -q tests/unit/test_github_connector.py tests/unit/test_web_connector.py tests/unit/test_confluence_connector.py` | PASS | 재실행 확인 — 127 passed |

## architecture 재검증

- [x] design.md에 적힌 레이어/파일이 실제 코드 위치와 일치한다
- [x] 역방향 참조(하위 레이어가 상위 레이어를 참조)가 생기지 않았다
- [x] design.md/task.md 범위에 없는 파일이 추가로 수정되지 않았다 (범위 이탈 여부)

(불일치 없음)

- `git diff --stat`으로 실제 수정 파일 확인: `src/rag_api/connectors/github.py`,
  `src/rag_api/connectors/web.py`, `tests/unit/test_github_connector.py`,
  `tests/unit/test_web_connector.py` — task.md T1/T2 "관련 파일" 범위와 정확히 일치,
  범위 이탈 없음. `src/rag_api/connectors/confluence.py`, `tests/unit/test_confluence_connector.py`는
  diff 없음(T3에서 명시한 읽기 전용 확인 대상과 일치).
- design.md의 `git diff` 내용(217/255번 라인 `title=Path(path).name`, web.py
  `_url_last_segment` 신규 함수 + 호출부 2곳 수정, `article h1`/`h1` 블록 삭제)이
  실제 diff와 정확히 일치.
- `src/rag_api/connectors/github.py`, `web.py`의 import를 Read/Grep으로 확인:
  두 파일 모두 `rag_api.infra.postgres`, `rag_api.infra.s3`, `rag_api.pipeline.steps.parse`,
  `rag_api.pipeline.utils.*`만 참조(하위 레이어 방향 유지). `rag_api.infra.postgres`,
  `rag_api.pipeline.steps.meta` 등에서 `connectors` 모듈을 import하는 역참조는 발견되지
  않음(`infra/postgres.py`의 "connectors" 문자열은 DB 테이블명이며 모듈 참조 아님).
- design.md가 두 파일을 "Pipeline (connectors)" 레이어로 표기한 것은 기존 코드베이스
  구조(`src/rag_api/connectors/`가 `src/rag_api/pipeline/`과 물리적으로는 별도 디렉터리이나
  Dagster/API가 아닌 문서 처리 순수 함수 계층으로 이미 분류되어 있음)를 그대로 반영한
  것이며, 이번 spec에서 새로 만든 구조가 아니므로 불일치로 보지 않음.

## 전체 회귀 검증

| 검사 | 결과 |
|---|---|
| `make test` | PASS |
| `make lint` | PASS |
| `make typecheck` | PASS |

(실패 없음 — 실패 상세 표 생략)

**판정**: PASS

## 결론

- [x] 전체 AC 통과 + 전체 회귀 검증 통과 — index.md 상태를 `validated`로 전환 가능
- [ ] 일부 실패 — 아래 세 목록을 command가 그대로 사용자에게 전달하고 처리

**[설계] 실패** (없으면 "(없음)")
- (없음)

**[구현] 실패 — Task 되돌림 대상** (없으면 "(없음)")
- (없음)

**매핑 없는 회귀 실패** (없으면 "(없음)")
- (없음)
