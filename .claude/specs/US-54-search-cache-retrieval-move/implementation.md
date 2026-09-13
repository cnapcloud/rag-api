# US-54: 검색 캐시 설정을 retrieval 하위로 이동 + 개명 — 구현 기록

> 담당: `implementer` · spec 워크플로우 3단계 실행 · 템플릿: `.claude/templates/implementation.md`

**대상**: [design.md](design.md) / [task.md](task.md)

## Task 현황

| ID | 상태 |
|---|---|
| T1 | done |
| T2 | done |
| T3 | done |
| T4 | done |
| T5 | done |

## 진행 기록

```
- **[T1] done** — AC: F1-1, F1-2 — 테스트: `uv run pytest tests/unit/test_settings.py -q` — 59 passed
- **[T2] done** — AC: F1-3, C2 — 테스트: `uv run pytest tests/unit/test_kb_settings_api.py -q` — 22 passed
- **[T3] done** — AC: F3-1(일부) — 테스트: `uv run pytest tests/integration/test_search_api.py tests/integration/test_search_cache_admin_api.py -q` — 14 passed
- **[T4] done** — AC: F2-1, F2-2 — grep으로 top-level `search_cache:` 부재 확인 +
  `Settings.model_validate(yaml.safe_load(...))`로 settings.example.yaml/docker/settings.yaml
  각각 `retrieval.cache` 값이 이동 전과 동일함을 확인(enabled=False, ttl_seconds=3600,
  max_entries=1000, match_mode=exact, semantic_threshold=0.95). settings.yaml은
  test_settings.py 회귀로 커버.
- **[T5] done** — AC: C1, C3, F3-1(전체) — data-schema.md 294~297행 재검토: 설정 필드
  위치 언급 없음 확인, 수정 불필요(C1). 사실 드리프트 수정: `tests/unit/test_search_cache_query.py`가
  개명 전 `SearchCacheSettings`를 직접 import해 컬렉션 에러가 났음 — task.md/design.md는 이
  파일을 "검토만·무변경"으로 명시했으나 T1의 클래스 개명(`SearchCacheSettings` → `CacheSettings`)
  결과 실제로는 참조가 깨져 있었다(design.md가 놓친 사실 — 레이어/AC 매핑 자체는 유효). import
  및 `_cfg` 헬퍼의 타입 힌트만 `CacheSettings`로 교체. 테스트:
  `uv run pytest tests/unit/test_settings.py tests/unit/test_kb_settings_api.py tests/unit/test_search_cache_infra.py tests/unit/test_search_cache_query.py tests/unit/test_doc_state_cache_invalidation.py tests/integration/test_search_api.py tests/integration/test_search_cache_admin_api.py tests/unit/test_kb_api.py -q`
  — 135 passed. 전체 스위트: `uv run pytest -q` — 739 passed, 1 skipped. `uv run ruff check .` —
  All checks passed.
```
