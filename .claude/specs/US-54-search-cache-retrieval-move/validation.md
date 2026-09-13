# US-54: 검색 캐시 설정을 retrieval 하위로 이동 + 개명 — 검증 결과

> 담당: `validator` · spec 워크플로우 4단계(최종) · 템플릿: `.claude/templates/validation.md`

**대상**: [spec.md](spec.md) / [design.md](design.md) / [task.md](task.md)

## 완료 기준 검증

| AC | 검증 방법 | 결과 | 비고 |
|---|---|---|---|
| F1-1 | `uv run pytest tests/unit/test_settings.py -q` + `settings.py` 코드 확인(`Settings`에 `search_cache` 필드 없음, `RetrievalSettings.cache: CacheSettings` 존재) | PASS | |
| F1-2 | `uv run pytest tests/unit/test_settings.py -q` (5개 키 `validate_override_key` 거부 케이스 포함) | PASS | |
| F1-3 | `uv run pytest tests/unit/test_kb_settings_api.py -q` (`retrieval.cache.*` 5개 키 overridable=False 확인) | PASS | |
| F2-1 | `grep -n '^search_cache:' settings.yaml settings.example.yaml docker/settings.yaml` — 매치 없음(exit 1) + 세 파일 모두 `retrieval:` 하위 `cache:` 블록 존재 확인 | PASS | |
| F2-2 | T4 구현 기록의 `Settings.model_validate` 값 확인 + `uv run pytest tests/unit/test_settings.py -q`(settings.yaml 로드 경로 커버) | PASS | |
| F3-1 | `uv run pytest tests/integration/test_search_api.py tests/integration/test_search_cache_admin_api.py -q` | PASS | |
| C1 | `docs/internal/design/data-schema.md` 294~297행 재확인 — 모듈 경로(`query/search_cache.py`, `infra/search_cache.py`)만 언급, 설정 필드 위치 언급 없음 → 수정 불필요 결론 유효 | PASS | |
| C2 | `tests/unit/test_kb_settings_api.py`의 F1-3 테스트가 `retrieval.*` 하위 5개 cache 필드 전부 deny + `auto_merge`만 override 허용 상태를 함께 확인 | PASS | |
| C3 | `uv run pytest tests/unit/test_settings.py tests/unit/test_kb_settings_api.py tests/unit/test_search_cache_infra.py tests/unit/test_search_cache_query.py tests/unit/test_doc_state_cache_invalidation.py tests/integration/test_search_api.py tests/integration/test_search_cache_admin_api.py tests/unit/test_kb_api.py -q` (135 passed) + `make test`(`uv run pytest -q`, 739 passed, 1 skipped) | PASS | |

## architecture 재검증

- [x] design.md에 적힌 레이어/파일이 실제 코드 위치와 일치한다 — `CacheSettings`가
      `RetrievalSettings` 정의 앞(269행)으로 이동, `RetrievalSettings.cache` 필드 존재,
      `Settings`에서 최상위 `search_cache` 필드 삭제 확인.
- [x] 역방향 참조(하위 레이어가 상위 레이어를 참조)가 생기지 않았다 — Config 내부
      재배치 + `api/routers/search.py`(API)의 `settings.retrieval.cache` 참조 1곳만
      존재. 프로덕션 코드 전체 grep 결과 `settings.search_cache` 잔존 참조 없음(`query/
      search_cache.py`, `infra/search_cache.py`는 동명이인 모듈로 설정 필드와 무관).
- [x] design.md/task.md 범위에 없는 파일이 추가로 수정되지 않았다 — `git diff main
      --name-only`로 확인한 변경 파일(`src/rag_api/config/settings.py`,
      `src/rag_api/api/routers/search.py`, `tests/integration/test_search_api.py`,
      `tests/integration/test_search_cache_admin_api.py`, `tests/unit/
      test_kb_settings_api.py`, `tests/unit/test_search_cache_query.py`, `tests/unit/
      test_settings.py`)이 task.md의 관련 파일 목록과 일치한다. `test_search_cache_query.py`
      수정은 task.md에 "검토만"으로 적혀 있었으나, 구현 기록(implementation.md T5)에
      design.md가 놓친 실제 import 드리프트(`SearchCacheSettings` 직접 import) 수정으로
      기록돼 있어 범위 이탈이 아니라 설계 누락의 정당한 보정으로 판단.

(불일치 없음)

## 결론

- [x] 전체 AC 통과 — index.md 상태를 `done`으로 전환 가능
- [ ] 일부 실패

(실패 목록 없음)
