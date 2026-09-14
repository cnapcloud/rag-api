# US-55: 검색 캐시 lookup/store 데코레이터 통합 + 캐시 게이트 훅(set_cache_gate) 추가 — Task 분리 및 구현 방법

> 담당: `designer` · spec 워크플로우 2단계 산출물(3단계 implementer 입력) · 템플릿:
> `.claude/templates/task.md`

**대상**: [design.md](design.md)

## Task 목록

| Task | 제목 | 대상 완료 기준 (AC) | 관련 파일 | 의존 |
|---|---|---|---|---|
| T1 | `search_cache`에 게이트 훅 + 공통 판단 헬퍼 추가 | F1-1, F1-2, F1-3, F1-4, F2-1 | `src/rag_api/query/search_cache.py`, `tests/unit/test_search_cache_query.py` | 없음 |
| T2 | 라우터를 무조건 호출 방식으로 단순화 + 기존 동작 보존 검증 | F3-1, F3-2, F3-3, F3-4, F3-5, C1 | `src/rag_api/api/routers/search.py`, `tests/unit/test_search_cache_query.py`, `tests/integration/test_search_cache_admin_api.py` | T1 |

## 완료 기준 커버리지

| 완료 기준 (AC) | 담당 Task |
|---|---|
| F1-1 | T1 |
| F1-2 | T1 |
| F1-3 | T1 |
| F1-4 | T1 |
| F2-1 | T1 |
| F3-1 | T2 |
| F3-2 | T2 |
| F3-3 | T2 |
| F3-4 | T2 |
| F3-5 | T2 |
| C1 | T2 |

## T1. `search_cache`에 게이트 훅 + 공통 판단 헬퍼 추가

**대상 완료 기준**: F1-1, F1-2, F1-3, F1-4, F2-1
**의존**: 없음
**관련 파일**:
- (수정) `src/rag_api/query/search_cache.py`
- (신규/수정) `tests/unit/test_search_cache_query.py`

구현 방법:
1. `search_cache.py` 상단에 모듈 레벨 상태 추가:
   ```python
   from typing import Callable

   _cache_gate: Callable[[list[str]], bool] | None = None

   def set_cache_gate(fn: Callable[[list[str]], bool] | None) -> None:
       """캐시 게이트 훅을 등록/해제한다. `fn(kb_ids) -> bool`이 False를 반환하면 그 요청은
       `cache_cfg.enabled`와 무관하게 캐시 조회/저장을 모두 건너뛴다. `None`으로 호출하면
       훅을 해제하고 기존(cache_cfg.enabled만 보는) 동작으로 되돌린다."""
       global _cache_gate
       _cache_gate = fn
   ```
2. 공통 판단 헬퍼 추가:
   ```python
   def _cache_usable(kb_ids: list[str], cfg: SearchCacheSettings) -> bool:
       """lookup/store가 공유하는 단일 판단 지점 (F2-1). cfg.enabled가 False면 그 자체로
       False. True인 경우에만 게이트 훅을 본다 — 훅이 없으면 그대로 True(F1-1)."""
       if not cfg.enabled:
           return False
       if _cache_gate is None:
           return True
       return _cache_gate(kb_ids)
   ```
   (참고: `SearchCacheSettings`는 이미 `TYPE_CHECKING` 블록에서 import돼 있다 — 타입
   힌트로만 쓰므로 런타임 import 추가 불필요)
3. `lookup` 함수의 기존 `try:` 블록 맨 첫 줄에 게이트 체크를 추가한다:
   ```python
   try:
       if not _cache_usable(kb_ids, cfg):
           return None, None
       bucket_hash = build_bucket_hash(kb_ids, effective_options)
       ...
   ```
   - 훅이 예외를 던져도 이 줄이 기존 `except Exception` 블록 안에 있으므로 자동으로
     fail-open 처리된다(design.md 에러 모델) — 별도 try/except 추가 금지.
   - `cfg.enabled=True`이고 훅이 없거나 훅이 `True`를 반환하면 기존 로직이 그대로 실행돼
     F1-3을 만족한다.
4. `store` 함수의 기존 `try:` 블록 맨 첫 줄에도 동일하게 추가한다:
   ```python
   try:
       if not _cache_usable(kb_ids, cfg):
           return
       bucket_hash = build_bucket_hash(kb_ids, effective_options)
       ...
   ```
5. 신규/수정 단위 테스트 (`tests/unit/test_search_cache_query.py`, 각 테스트 종료 시
   `search_cache.set_cache_gate(None)`으로 반드시 리셋 — 모듈 전역 상태이므로 테스트 간
   누수 방지가 필수):
   - F1-1: 훅 미등록 + `cfg.enabled=True` → `lookup`/`store`가 훅 등록 이전과 동일하게
     동작(기존 테스트가 이미 커버 — 회귀 확인만).
   - F1-2: `set_cache_gate(lambda kb_ids: False)` 등록 후 `cfg.enabled=True`여도 `lookup`이
     `(None, None)`을 반환하고 `infra_cache.get_entry`가 호출되지 않는지, `store` 호출 시
     `infra_cache.set_entry`가 호출되지 않는지 mock으로 검증.
   - F1-3: `set_cache_gate(lambda kb_ids: True)` 등록 후 `cfg.enabled=True`면 훅 미등록
     때와 동일하게 `infra_cache` 호출이 발생하는지 검증.
   - F1-4: 훅 등록 후 `set_cache_gate(None)`으로 해제하면 F1-1과 동일한 동작으로 돌아오는지
     검증.
   - F2-1: 같은 `(kb_ids, cfg.enabled, 훅 상태)` 조합에서 `_cache_usable` 결과가 `lookup`
     경로와 `store` 경로에서 일치하는지(동일 헬퍼를 호출하므로 자명하지만, 회귀 방지용
     테스트로 명시).

## T2. 라우터를 무조건 호출 방식으로 단순화 + 기존 동작 보존 검증

**대상 완료 기준**: F3-1, F3-2, F3-3, F3-4, F3-5, C1
**의존**: T1 (게이트 판단 로직이 `search_cache.lookup`/`store` 내부로 들어와 있어야 라우터를
단순화해도 `cfg.enabled=False` 시 Redis 접근이 없다는 보장이 성립)
**관련 파일**:
- (수정) `src/rag_api/api/routers/search.py`
- (수정, 필요 시) `tests/unit/test_search_cache_query.py`
- (수정, 필요 시) `tests/integration/test_search_cache_admin_api.py`

구현 방법:
1. `search()` 핸들러에서 `if cache_cfg.enabled:` 로 감싸 `search_cache.lookup(...)`을
   호출하던 블록을 무조건 호출로 변경한다:
   ```python
   cached, query_embedding = search_cache.lookup(
       req.query, req.kb_ids, effective_options, cache_cfg,
   )
   if cached is not None:
       cached["meta"]["cache_status"] = "hit"
       return SearchResponse(**cached)
   ```
   (T1에서 `lookup`이 `cfg.enabled=False`면 즉시 `(None, None)`을 반환하므로 결과는
   기존과 동일 — F3-2 보존)
2. `meta.cache_status` 계산 줄(`"miss" if cache_cfg.enabled else "disabled"`)은 그대로
   둔다 — 이 값은 게이트가 아니라 `cache_cfg.enabled`만 봐야 하므로(F3-3) 손대지 않는다.
3. 응답 반환 직전 `if cache_cfg.enabled:` 로 감싸 `search_cache.store(...)`를 호출하던
   블록도 무조건 호출로 변경한다:
   ```python
   search_cache.store(
       req.query, req.kb_ids, effective_options, cache_cfg,
       response.model_dump(), query_embedding,
   )
   ```
4. 회귀 검증 (리스크&롤백에서 식별한 회귀 위험 — 기존 프로덕션 코드 수정이므로 아래
   전체 스위트 확인이 이 task에 필수):
   - F3-1/F3-2/F3-3/F3-4: 기존 `tests/unit/test_search_cache_query.py`,
     `tests/integration/test_search_cache_admin_api.py`의 exact/semantic hit·miss,
     `cache_cfg.enabled=False` 시 Redis 미접근, `cache_status` 값, 로그 문구 검증 테스트를
     그대로 실행해 통과 확인(깨지면 T1의 게이트 삽입 위치가 기존 분기 순서를 바꾼 것이므로
     원인 파악 후 최소 수정).
   - F3-5: US-53/US-54 테스트 전체(`tests/unit/test_search_cache_infra.py` 포함) 재실행,
     필요한 최소 수정(예: import 경로, mock 대상 함수명 변경)만 반영.
   - C1: `uv run pytest`로 관련 테스트 디렉터리(`tests/unit/test_search_cache_query.py`,
     `tests/unit/test_search_cache_infra.py`, `tests/integration/test_search_cache_admin_api.py`)
     뿐 아니라 `/api/search` 관련 통합 테스트 전체까지 통과 확인 — 라우터 프로덕션 코드를
     수정했으므로 이 task에서는 관련 테스트 전체 스위트 통과를 최종 확인한다.
