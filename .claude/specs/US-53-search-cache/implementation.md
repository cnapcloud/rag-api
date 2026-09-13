# US-53: 검색 응답 캐싱 — Redis 큐+캐시 겸용 확장 — 구현 기록

> 담당: `implementer` · spec 워크플로우 3단계 실행 · 템플릿: `.claude/templates/implementation.md`

**대상**: [design.md](design.md) / [task.md](task.md)

## Task 현황

| ID | 상태 | 비고 |
|---|---|---|
| T1 | done | |
| T2 | done | |
| T3 | done | |
| T4 | done | |
| T5 | done | |
| T6 | done | |
| T7 | done | |

## 진행 기록

```
- **[T1] done** — AC: F1-1 — 테스트: `uv run pytest -q tests/unit/test_settings.py` — 54 passed
- **[T2] done** — AC: F1-3, F1-4, F2-1, F2-2 — 테스트:
  `uv run pytest -q tests/unit/test_search_cache_infra.py tests/unit/test_queue_worker.py` —
  11 + 12 passed. 전체 회귀 확인: `uv run pytest -q` — 701 passed, 1 skipped. `uv run ruff
  check`도 통과. 구현 노트: design.md/task.md는 `SETEX`를 명시했으나 redis-py에서 deprecated
  경고가 발생해 동일 의미의 `client.set(key, value, ex=ttl_seconds)`로 구현(F1-3 AC의 "TTL
  경과 후 자동 만료" 동작 자체는 동일, 사실상 표기 차이). `get_redis_client` 사용은
  design.md에 명시되지 않은 세부사항이라 기존 코드베이스 관례(`pipeline/queue/enqueue.py`,
  `queue_worker.py`)를 따라 각 함수 내부에서 지연 import했다(모듈 top-level import 시
  `patch("rag_api.infra.redis.get_redis_client", ...)`로 테스트 패치가 되지 않는 문제 회피).
  이번 세션은 여기까지 진행 후 사용자 지시로 중단 — T3부터는 blocked 아닌 단순 미착수 상태.
- **[T3] done** — AC: F3-1, F3-2, F3-5, F3-6 — 테스트:
  `uv run pytest -q tests/unit/test_retriever_auto_merge.py tests/unit/test_search_cache_infra.py
  tests/unit/test_search_cache_query.py` — 34 passed. `uv run ruff check`도 통과. 구현은
  task.md 그대로 따름(`query/retriever.py`에 `query_embedding` 파라미터 추가,
  `query/search_cache.py` 신규 — `build_bucket_hash`/`build_query_hash`/`cosine_similarity`/
  `lookup`/`store`/`invalidate_kb`/`invalidate_all`/`invalidate_kb_best_effort`). 특이사항 없음.
- **[T4] done** — AC: F1-2, F3-3, F3-4 — 테스트: `uv run pytest -q
  tests/integration/test_search_api.py` — 8 passed. `uv run ruff check`도 통과. task.md 그대로
  구현(`SearchMeta.cache_status` 추가, `search()` 핸들러에 lookup/store 연동, 기존
  `mock_settings` 두 곳에 `search_cache.enabled = False` 추가, 신규 hit/miss/disabled
  통합 테스트 3개 추가). 특이사항 없음.
- **[T5] done** — AC: F4-1, F4-2, F4-3 — 테스트: `uv run pytest -q
  tests/unit/test_doc_state_cache_invalidation.py tests/unit/test_kb_api.py` — 13 passed.
  `uv run ruff check`도 통과. task.md 그대로 구현(`doc_state.py::set_indexed`에 `kb_id` 키워드
  인자 추가, `runner.py`/`ingest_ops.py`의 두 호출부 모두 `kb_id` 전달, `delete.py::delete_doc`
  끝에 `invalidate_kb_best_effort` 추가, `kb.py::delete_kb`의 `delete_kb_meta` 직후 추가).
  구현 노트: 기존 `tests/unit/test_kb_api.py`의 `delete_kb` 성공 경로 테스트 3개가 Redis를
  mock하지 않고 있어 새 `invalidate_kb_best_effort` 호출이 실제 Redis 연결을 시도해 테스트가
  느려지는 문제가 있었다(conventions 스킬의 "테스트에서 실제 인프라 연결 금지" 위반 위험) —
  design.md/task.md에 명시된 범위는 아니지만 이 세 테스트에 `invalidate_kb_best_effort`
  mock을 추가해 해결(사실상 버그 수정, task.md 관련 파일 목록에 없던 `tests/unit/test_kb_api.py`
  추가 수정).
- **[T6] done** — AC: F5-1, F5-2, F5-3 — 테스트: `uv run pytest -q
  tests/integration/test_search_cache_admin_api.py` — 6 passed. `uv run ruff check`도 통과.
  task.md 그대로 구현(`DELETE /api/search/cache?kb_id=<optional>` 신규 엔드포인트, raw
  `invalidate_kb`/`invalidate_all` 사용). task.md가 요구한 세 케이스(F5-1/F5-2/F5-3) 외에
  Redis 장애 시 503 전파(design.md 에러 모델)와 hit→clear→miss e2e 시나리오(`mock_redis`
  픽스처 재사용)도 추가로 검증. 특이사항 없음.
- **[T7] done** — AC: C2 — task.md 그대로 구현: `docs/internal/architecture/README.md`의
  "저장소 역할 분리" 항목과 관련 표 설명을 갱신, `docs/internal/design/data-schema.md` §3
  제목/첫 문장을 갱신하고 신규 §3.1에 캐시 키 스킴(design.md 데이터 모델 그대로) 추가. diff
  리뷰로 "Redis 큐 전용"/"exclusively for the ingest" 문구가 두 파일 모두에서 더 이상
  남아있지 않음을 확인(수동 확인, C2 완료 기준 방식).
- **전체 완료 확인** — `make test`(`uv run pytest -q`): 734 passed, 1 skipped. `uv run ruff
  check .`: 전체 통과. `grep -r "from src\." src/ tests/`: 매치 없음. T1~T7 모두 blocked 없이
  done — US-53 구현 종료.
```
