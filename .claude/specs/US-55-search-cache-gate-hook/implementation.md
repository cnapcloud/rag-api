# US-55: 검색 캐시 lookup/store 데코레이터 통합 + 캐시 게이트 훅(set_cache_gate) 추가 — 구현 기록

> 담당: `implementer` · spec 워크플로우 3단계 실행 · 템플릿: `.claude/templates/implementation.md`

**대상**: [design.md](design.md) / [task.md](task.md)

## Task 현황

| ID | 상태 |
|---|---|
| T1 | done |
| T2 | done |

## 진행 기록

```
- **[T1] done** — AC: F1-1, F1-2, F1-3, F1-4, F2-1 — 테스트:
  `uv run pytest -q tests/unit/test_search_cache_query.py` — 47 passed
  (기존 39 + 신규 TestCacheGate 클래스 10개, 그중 훅 예외 fail-open 검증 2개 추가로
  design.md 에러 모델 커버). `src/rag_api/query/search_cache.py`에 `set_cache_gate`/
  `_cache_gate` 모듈 상태 + `_cache_usable(kb_ids, cfg)` 헬퍼를 추가하고, `lookup`/`store`의
  기존 `try:` 블록 첫 줄에 게이트 체크를 삽입했다(설계 그대로, 기존 로직/로그 문구 변경 없음).
- **[T2] done** — AC: F3-1, F3-2, F3-3, F3-4, F3-5, C1 — 테스트: `uv run pytest -q`
  (전체 스위트) — 753 passed, 1 skipped; `uv run ruff check .` — All checks passed.
  `src/rag_api/api/routers/search.py`에서 `if cache_cfg.enabled:`로 감싸던
  `search_cache.lookup`/`store` 호출을 무조건 호출로 단순화(설계 그대로), `cache_status`
  계산 줄은 그대로 유지.
  범위를 벗어난 추가 수정(사실 드리프트, task.md 대상 파일 목록 밖):
  `tests/integration/test_search_api.py`의 `TestSearchCacheIntegration::
  test_cache_disabled_skips_lookup_and_store`가 "`cache_cfg.enabled=False`면
  `search_cache.lookup`/`store` 자체가 호출되지 않는다"는, 이번 리팩터링으로 더 이상
  유효하지 않은 전제(이제는 함수가 항상 호출되고 내부에서 즉시 반환)를 검증하고 있어
  실패했다. design.md/task.md가 명시한 F3-2("Redis 접근이 전혀 없다")는 그대로 유효하므로,
  검증 지점을 `search_cache.lookup`/`store` mock에서 `infra_cache.get_entry`/`set_entry`
  mock으로 바꿔 Redis 미접근을 직접 검증하도록 수정했다(AC 매핑/레이어는 변경 없음).
```
