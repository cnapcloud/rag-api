# US-NN: <제목> — 검증 결과

> 담당: `validator` · spec 워크플로우 4단계(최종) · 템플릿: `.claude/templates/validation.md`

**대상**: [spec.md](spec.md) / [design.md](design.md) / [task.md](task.md)

## 완료 기준 검증

| AC | Task | 검증 방법 | 결과 | 비고 |
|---|---|---|---|---|
| F1-1 | T1 | `uv run pytest -q tests/unit/test_search_cache_query.py::TestCacheGate` | PASS | |
| F1-2 | T1 | `uv run pytest -q tests/unit/test_search_cache_query.py::TestCacheGate` | FAIL | `[구현]` — `test_hook_returns_false`, `test_hook_returns_false_with_multiple_kb_ids` 2건 실패(훅이 `False`를 반환해도 캐시가 여전히 사용됨) |
| F2-1 | T1 | (architecture 재검증에서 역방향 참조 발견) | FAIL | `[설계]` — `query/search_cache.py`가 `api/routers/search.py`를 import(역방향 참조), design.md 레이어 판단 재검토 필요 |

## architecture 재검증

- [ ] design.md에 적힌 레이어/파일이 실제 코드 위치와 일치한다
- [ ] 역방향 참조(하위 레이어가 상위 레이어를 참조)가 생기지 않았다
- [ ] design.md/task.md 범위에 없는 파일이 추가로 수정되지 않았다 (범위 이탈 여부)

<불일치 내용 (없으면 "(불일치 없음)")>

## 전체 회귀 검증

| 검사 | 결과 |
|---|---|
| `make test` | PASS |
| `make lint` | PASS |
| `make typecheck` | FAIL |

<실패 상세 (없으면 표 생략)>

| 검사 | 실패 위치 | 이유 | 매핑 |
|---|---|---|---|
| `make typecheck` | `src/rag_api/infra/search_cache.py:100` | `zrem` 인자 타입 불일치 | 없음 |
| `make typecheck` | `src/rag_api/query/search_cache.py:24` | `SearchCacheSettings` 속성 없음(`CacheSettings`로 개명됨) | T1 |

**판정**: FAIL — 실패 2건(매핑됨 1건 → T1, 매핑 없음 1건 → 사용자 확인 필요)

## 결론

- [ ] 전체 AC 통과 + 전체 회귀 검증 통과 — index.md 상태를 `validated`로 전환 가능
- [x] 일부 실패 — 아래 세 목록을 command가 그대로 사용자에게 전달하고 처리

**[설계] 실패** (없으면 "(없음)")
- <AC ID> — <이유>

**[구현] 실패 — Task 되돌림 대상** (없으면 "(없음)")
- T1 — 근거: AC F1-2 — `test_hook_returns_false`, `test_hook_returns_false_with_multiple_kb_ids` 2건 실패(훅이 `False`를 반환해도 캐시가 여전히 사용됨)
- T1 — 근거: 회귀검사 `make typecheck` `src/rag_api/query/search_cache.py:24` — `SearchCacheSettings` 속성 없음(`CacheSettings`로 개명됨)

**매핑 없는 회귀 실패** (없으면 "(없음)")
- `make typecheck` `src/rag_api/infra/search_cache.py:100` — `zrem` 인자 타입 불일치
