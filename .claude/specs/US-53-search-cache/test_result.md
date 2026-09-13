# US-53: 검색 응답 캐싱 — Redis 큐+캐시 겸용 확장 — 검증 결과

> 담당: `validator` · spec 워크플로우 4단계(최종) · 템플릿: `.claude/templates/test_result.md`

**대상**: [spec.md](spec.md) / [design.md](design.md) / [task.md](task.md)

## 완료 기준 검증

| AC | 검증 방법 | 결과 | 비고 |
|---|---|---|---|
| F1-1 | `uv run pytest -q tests/unit/test_settings.py` | PASS | 기본값(enabled=false/ttl=3600/max_entries=1000/match_mode=exact/threshold=0.95) + override 확인 |
| F1-2 | `uv run pytest -q tests/integration/test_search_api.py::TestSearchCacheIntegration::test_cache_disabled_bypasses_cache_entirely` | PASS | `enabled=False`일 때 `lookup`/`store` 미호출, `cache_status=disabled` |
| F1-3 | `uv run pytest -q tests/unit/test_search_cache_infra.py` (`test_entry_expires_after_ttl`, `test_set_entry_uses_configured_ttl`) | PASS | |
| F1-4 | `uv run pytest -q tests/unit/test_search_cache_infra.py::TestEviction::test_eviction_removes_oldest_when_over_max_entries` | PASS | FIFO 축출 확인 |
| F2-1 | `uv run pytest -q tests/unit/test_search_cache_infra.py::test_cache_key_prefixes_do_not_collide_with_queue_keys` | PASS | `rag:cache:*` vs `rag:upload:*`/`rag:delete:*` 실제 키 상수(`enqueue.py`) 대조 확인 |
| F2-2 | `uv run pytest -q` 전체 회귀 (734 passed, 1 skipped) | PASS | 기존 큐 테스트(`test_queue_worker.py` 등) 회귀 없음 |
| F3-1 | `uv run pytest -q tests/unit/test_search_cache_query.py::TestBuildBucketHash::test_different_option_value_yields_different_bucket_hash` | PASS | |
| F3-2 | `...test_kb_ids_order_does_not_affect_bucket_hash` | PASS | |
| F3-3 | `uv run pytest -q tests/integration/test_search_api.py::TestSearchCacheIntegration::test_cache_hit_skips_retriever_and_reports_hit` | PASS | hit 시 `retriever.query` 미호출 확인(mock assert_not_called) |
| F3-4 | 위 테스트 + `test_cache_miss_calls_retriever_and_stores` | PASS | hit/miss/disabled 각각 `cache_status` 값 확인 |
| F3-5 | `tests/unit/test_search_cache_query.py::TestLookupSemantic::test_similarity_above_threshold_is_hit` / `test_similarity_below_threshold_is_miss` | PASS | 임베딩 재사용(mock) 및 threshold 경계 확인 |
| F3-6 | `tests/unit/test_search_cache_query.py::TestLookupExact::test_exact_mode_never_computes_embedding` | PASS | exact 모드에서 임베딩 계산 자체가 발생하지 않음 확인 |
| F4-1 | `uv run pytest -q tests/unit/test_doc_state_cache_invalidation.py::TestSetIndexed` | PASS | `set_indexed(kb_id=...)` → `invalidate_kb_best_effort` 호출 확인, `kb_id` 없으면 스킵 확인 |
| F4-2 | `tests/unit/test_doc_state_cache_invalidation.py::TestDeleteDoc` (soft/hard) | PASS | |
| F4-3 | `tests/unit/test_kb_api.py::TestDeleteKB` (`test_reloads_dagster_when_connector_had_schedule`, `test_invalidate_kb_failure_does_not_fail_delete`) | PASS | `delete_kb`가 `invalidate_kb_best_effort(kb_id)` 호출, 실패해도 200 |
| F5-1 | `tests/integration/test_search_cache_admin_api.py::test_clear_kb_returns_cleared_count`, `test_clear_kb_flips_previous_hit_to_miss` | PASS | |
| F5-2 | `tests/integration/test_search_cache_admin_api.py::test_clear_all_returns_cleared_count` | PASS | |
| F5-3 | `tests/integration/test_search_cache_admin_api.py::test_clear_kb_on_empty_cache_returns_zero`, `test_clear_all_on_empty_cache_returns_zero` | PASS | |
| C1 | `uv run pytest -q` (전체) | PASS | 734 passed, 1 skipped. `uv run ruff check .` 도 전체 통과 |
| C2 | 수동 확인 — `git diff docs/internal/architecture/README.md docs/internal/design/data-schema.md` 리뷰 | PASS | "Redis(인제스트·삭제 큐 전용)" → "…+ 검색 결과 캐시 겸용" 갱신 확인, data-schema.md §3 제목/서술 갱신 + §3.1 캐시 키 스킴 추가 확인. "exclusively"/"큐 전용" 잔존 문구 없음 |

## architecture 재검증

- [x] design.md에 적힌 레이어/파일이 실제 코드 위치와 일치한다 — `infra/search_cache.py`(Redis I/O), `query/search_cache.py`(도메인 로직), `api/routers/search.py`(연동+엔드포인트), `config/settings.py`/`settings.yaml`, `pipeline/utils/doc_state.py`·`pipeline/runner.py`·`defs/ops/ingest_ops.py`·`pipeline/steps/delete.py`·`api/routers/kb.py`(F4 훅), `docs/internal/architecture/README.md`·`docs/internal/design/data-schema.md`(C2) 전부 실제 코드/문서와 diff 대조로 일치 확인.
- [x] 역방향 참조가 생기지 않았다 — import 방향을 직접 확인:
  - `api/routers/kb.py`(API) → `query/search_cache.py`(Query): 표준 하향 참조, 문제없음.
  - `pipeline/utils/doc_state.py`, `pipeline/steps/delete.py`(Pipeline) → `query/search_cache.py`(Query): `architecture` 스킬의 압축 레이어표는 Pipeline/Query를 "API 아래, Infra 위"의 동일 계층으로 묶어 취급하므로(스킬 원문: `CLI → API → Pipeline/Query → Infra`), 같은 계층 내 상호 참조는 이 스킬 기준으로는 "역방향"이 아니다. design.md가 든 기존 선례(`query/retriever.py`가 이미 `pipeline/utils/sparse.py`를 참조)도 실제 코드에서 확인됨(`from rag_api.pipeline.utils.sparse import compute_sparse_tf`). 다만 `docs/internal/architecture/application.md` §1/§2의 상세 다이어그램은 `CLI > API > Pipeline > Query > Infra` 순서로 더 세분화해 그리고 있어, 그 기준으로는 Query→Pipeline(기존 선례) 방향이 오히려 더 어긋나 보일 수 있다 — 이는 이번 US 이전부터 존재하던 기존 코드 관례이고, 이번 변경(Pipeline→Query)은 그 세분화 기준으로 보면 오히려 상위→하위 방향이라 문제가 없다. 두 문서 간의 이 미세한 불일치는 이번 US 범위 밖의 기존 이슈로 간주하고 블로킹하지 않았다(design.md에서 이미 이 판단 근거를 명시적으로 제시했고, 스킬 기준 재검증 결과 결론이 바뀌지 않음).
  - 결론: 역방향 참조 없음 판정 유지.
- [x] design.md/task.md 범위에 없는 파일이 추가로 수정되지 않았다 — `git diff main...HEAD --stat` + 현재 uncommitted diff를 design.md "영향 레이어/파일" 표와 대조, 전량 일치. 유일한 예외: `tests/unit/test_kb_api.py`(design.md 파일 표에 없음) — implementation.md에 T5 진행 중 발견한 테스트 인프라 버그(기존 `delete_kb` 성공 경로 테스트가 Redis를 mock하지 않아 신규 `invalidate_kb_best_effort` 호출이 실제 연결을 시도)를 고치기 위해 mock을 추가한 것으로, 프로덕션 코드 변경이나 레이어 결정과 무관한 테스트 전용 보강이며 implementation.md에 이미 투명하게 기록됨 — 범위 이탈로 보지 않음.

(불일치 없음)

## 결론

- [x] 전체 AC 통과 — spec.md **상태**를 `done`으로 전환 가능
- [ ] 일부 실패
