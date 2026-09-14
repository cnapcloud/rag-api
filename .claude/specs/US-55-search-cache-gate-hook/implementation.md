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
- **[T1] done** (재시도) — AC: F1-1, F1-2, F1-3, F1-4, F2-1 — 위 blocked 사유 2건을
  사실 드리프트로 수정: `src/rag_api/query/search_cache.py`의 `TYPE_CHECKING` import와
  세 곳의 파라미터 타입 힌트를 `SearchCacheSettings` → `CacheSettings`로 변경(main에서
  US-54가 개명한 이름을 그대로 반영, 레이어/AC 매핑 변경 없음).
  `tests/unit/test_search_cache_query.py`의
  `test_cache_usable_matches_across_lookup_and_store_paths`에서 `lambda kb_ids,
  r=hook_result: r` 대신 `fixed_result: bool = hook_result`로 값을 좁힌 뒤 명시적으로
  타입 애노테이션한 내부 함수 `_hook(kb_ids: list[str]) -> bool`을 정의해 mypy가
  추론할 수 있게 함(이전에 시도했다가 되돌려진 람다 애노테이션 방식 대신 named
  function으로 재발 방지). 테스트: `uv run mypy
  src/rag_api/query/search_cache.py tests/unit/test_search_cache_query.py` — 0 errors;
  `uv run pytest -q tests/unit/test_search_cache_query.py` — 30 passed.
```

## 외부 이상 징후

같은 CI 실행(PR #2, `make typecheck`)에서 나온 실패 중 task.md의 Task 관련 파일에
매핑되지 않는 것들 — design.md도 이 파일들을 "변경 없음"으로 명시함(US-55 범위 밖).

```
- `make typecheck` — `src/rag_api/infra/search_cache.py:100,102,103,106,107,109,120,136,137,138,139` — `zrem`/`srem`/`partition`/`_entry_key`/`_bucket_key` 인자가 redis 반환값(`bytes | str | tuple | list`)과 타입이 안 맞음(11건)
  — **처리 결과 (사용자 확인 후 같이 고침)**: `infra/redis.py`의 클라이언트는
  `decode_responses=True`로 생성되므로 런타임엔 항상 `str`이지만, redis-py 스텁의
  `zrange`/`smembers` 반환 타입이 withscores 등 오버로드를 포괄하는 넓은 유니언이라
  mypy가 좁히지 못함. `Redis[str]` 제네릭 파라미터화는 redis-py 스텁이 지원하지 않아
  (`"Redis" expects no type arguments`) 되돌리고, 대신 `search_cache.py`의 3개
  호출부(`evict_if_needed`의 `oldest[0]`, `get_bucket_query_hashes`의 `smembers`,
  `invalidate_kb`의 `smembers`)에 `typing.cast`로 좁히는 주석 처리를 추가. `uv run mypy
  src/rag_api/infra/search_cache.py src/rag_api/infra/redis.py` — 0 errors.
- `make typecheck` — `src/rag_api/query/retriever.py:223` — `Incompatible types in assignment (expression has type "str", variable has type "QueryBundle")`
  — **처리 결과 (사용자 확인 후 같이 고침)**: `retrieve_input` 변수에 명시적
  `QueryBundle | str` 타입 애노테이션을 추가(`TYPE_CHECKING` 블록에서 `QueryBundle`
  import, 런타임 import는 기존처럼 조건문 내부에 유지)해 mypy가 두 분기의 대입을 모두
  허용하도록 함. `uv run mypy src/rag_api/query/retriever.py` — 0 errors.

두 항목 모두 `make typecheck` 전체 재확인(0 errors, 158 files) + `make test`(753 passed,
1 skipped) + `uv run ruff check .`(All checks passed)로 회귀 없음을 확인했다.
```
