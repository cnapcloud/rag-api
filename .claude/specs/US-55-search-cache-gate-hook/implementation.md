# US-55: 검색 캐시 lookup/store 데코레이터 통합 + 캐시 게이트 훅(set_cache_gate) 추가 — 구현 기록

> 담당: `implementer` · spec 워크플로우 3단계 실행 · 템플릿: `.claude/templates/implementation.md`

**대상**: [design.md](design.md) / [task.md](task.md)

## Task 현황

| ID | 상태 |
|---|---|
| T1 | blocked |
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
- **[T1] blocked** — AC: F1-2, F2-1 — 유형: [구현] — `/spec-pr` merge 확인 경로에서
  PR #2 CI(`make typecheck`)가 실패(`FAILURE`)함. 실패 위치가 T1 관련 파일에 매핑됨:
  - `src/rag_api/query/search_cache.py:24` — `Module "rag_api.config.settings" has no
    attribute "SearchCacheSettings"; maybe "CacheSettings"?` — main에 먼저 merge된
    US-54가 `SearchCacheSettings`를 `CacheSettings`로 개명/이동했는데 이 브랜치는 옛
    이름을 그대로 참조하고 있음(main 통합 드리프트).
  - `tests/unit/test_search_cache_query.py:364` — `Cannot infer type of lambda` — 커밋
    d29a075에서 한 번 타입 애노테이션으로 고쳤다가 7fefdc1에서 되돌려져 재발함.
  다음 시도: 두 위치를 main의 `CacheSettings`/타입 애노테이션에 맞춰 고친 뒤
  `/spec-implement` 재실행.
```

## 외부 이상 징후

같은 CI 실행(PR #2, `make typecheck`)에서 나온 실패 중 task.md의 Task 관련 파일에
매핑되지 않는 것들 — design.md도 이 파일들을 "변경 없음"으로 명시함(US-55 범위 밖).

```
- `make typecheck` — `src/rag_api/infra/search_cache.py:100,102,103,106,107,109,120,136,137,138,139` — `zrem`/`srem`/`partition`/`_entry_key`/`_bucket_key` 인자가 redis 반환값(`bytes | str | tuple | list`)과 타입이 안 맞음(11건)
- `make typecheck` — `src/rag_api/query/retriever.py:223` — `Incompatible types in assignment (expression has type "str", variable has type "QueryBundle")`
```
