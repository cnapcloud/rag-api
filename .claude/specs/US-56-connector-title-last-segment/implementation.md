# US-56: GitHub/Web 커넥터 title 결정 방식 변경 — 구현 기록

> 담당: `implementer` · spec 워크플로우 3단계 실행 · 템플릿: `.claude/templates/implementation.md`

**대상**: [design.md](design.md) / [task.md](task.md)

## Task 현황

| ID | 상태 |
|---|---|
| T1 | done |
| T2 | done |
| T3 | done |

## 진행 기록

```
- **[T1] done** — AC: F1-1, F1-2, F1-3, F1-4 — 테스트: `uv run pytest -q tests/unit/test_github_connector.py` — 20 passed
- **[T2] done** — AC: F2-1, F2-2, F2-3, F2-4 — 테스트: `uv run pytest -q tests/unit/test_web_connector.py` — 69 passed
- **[T3] done** — AC: F3-1, F3-2, C1 — `src/rag_api/connectors/confluence.py`는 T1/T2 작업 중
  수정하지 않았음을 `git diff --stat`으로 확인(diff 없음). `tests/unit/test_confluence_connector.py`의
  기존 title 검증 테스트(line 213, `kwargs["title"] == "My Page"` — page["title"] 직접 사용
  확인)가 이미 F3-1을 충분히 커버해 신규 테스트는 추가하지 않음. 테스트:
  `uv run pytest -q tests/unit/test_github_connector.py tests/unit/test_web_connector.py tests/unit/test_confluence_connector.py`
  — 127 passed
```

## 외부 이상 징후

(없음)
