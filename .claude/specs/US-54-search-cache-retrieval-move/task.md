# US-54: 검색 캐시 설정을 retrieval 하위로 이동 + 개명 — Task 분리 및 구현 방법

> 담당: `designer` · spec 워크플로우 2단계 산출물(3단계 implementer 입력) · 템플릿:
> `.claude/templates/task.md`

**대상**: [design.md](design.md)

## Task 목록

| Task | 제목 | 대상 완료 기준 (AC) | 관련 파일 | 의존 |
|---|---|---|---|---|
| T1 | `CacheSettings`를 `retrieval` 하위로 이동 + 전체 오버라이드 deny 처리 | F1-1, F1-2 | `src/rag_api/config/settings.py`, `tests/unit/test_settings.py` | 없음 |
| T2 | 스키마 응답에서 `retrieval.cache.*` 오버라이드 불가 노출 확인 | F1-3, C2 | `tests/unit/test_kb_settings_api.py` | T1 |
| T3 | `search.py`의 설정 참조 경로 갱신 | F3-1 (일부) | `src/rag_api/api/routers/search.py`, `tests/integration/test_search_api.py`, `tests/integration/test_search_cache_admin_api.py` | T1 |
| T4 | 배포용 설정 파일 3종 갱신 | F2-1, F2-2 | `settings.yaml`, `settings.example.yaml`, `docker/settings.yaml` | T1 |
| T5 | 데이터 스키마 문서 재검토 + 전체 회귀 확인 | C1, C3, F3-1(전체) | `docs/internal/design/data-schema.md`(검토만), 전체 테스트 스위트 | T1, T2, T3, T4 |

## 완료 기준 커버리지

| 완료 기준 (AC) | 담당 Task |
|---|---|
| F1-1 | T1 |
| F1-2 | T1 |
| F1-3 | T2 |
| F2-1 | T4 |
| F2-2 | T4 |
| F3-1 | T3, T5 |
| C1 | T5 |
| C2 | T2 |
| C3 | T5 |

## T1. `CacheSettings`를 `retrieval` 하위로 이동 + 전체 오버라이드 deny 처리

**대상 완료 기준**: F1-1, F1-2
**의존**: 없음
**관련 파일**:
- (수정) `src/rag_api/config/settings.py`
- (수정) `tests/unit/test_settings.py`

구현 방법:
1. `src/rag_api/config/settings.py`에서 기존 `class SearchCacheSettings(BaseModel): ...`
   (283~299행 부근) 정의를 `class CacheSettings(BaseModel): ...`로 개명하고, `class
   RetrievalSettings` 정의(269행) **앞으로** 옮긴다(전방 참조 불가 — `RetrievalSettings`가
   `CacheSettings`를 필드 타입으로 참조하므로 클래스 정의 순서상 먼저 나와야 함).
2. 옮기면서 5개 필드(`enabled`/`ttl_seconds`/`max_entries`/`match_mode`/`semantic_threshold`)
   전부에 `json_schema_extra={"override": False}`를 추가한다(현재는 없음 — 이동 전엔
   `OVERRIDABLE_SETTINGS_PREFIXES`에 `search_cache.`가 없어 자동으로 막혔지만, 이동 후
   `retrieval.`은 이미 allow-list에 있으므로 명시 deny가 없으면 F1-2가 깨진다). 정확히
   `RerankerSettings`(205~234행)와 같은 패턴을 따른다. docstring도 "검색 응답 캐시 —
   US-53, US-54(retrieval 하위로 이동)" 정도로 갱신하고 "retrieval.* 중 오버라이드가 열린
   유일한 섹션은 auto_merge뿐"이라는 기존 서술(auto_merge 클래스 docstring, 260~262행)과
   모순되지 않는지 확인한다(cache는 deny이므로 모순 없음, 오히려 C2를 강화).
3. `RetrievalSettings`(구 269행) 본문 끝에 `cache: CacheSettings = Field(default_factory=CacheSettings)`
   필드를 추가한다.
4. `Settings` 클래스(412행 부근)에서 `search_cache: SearchCacheSettings = Field(default_factory=SearchCacheSettings)`
   라인을 삭제한다(F1-1 — 최상위에 더는 존재하지 않아야 함).
5. `tests/unit/test_settings.py`의 `test_search_cache_settings_defaults`(609행)와
   `test_search_cache_settings_override_from_yaml`(620행)을 `Settings().search_cache` →
   `Settings().retrieval.cache`, YAML 최상위 `search_cache:` 블록 → `retrieval:\n  cache:`
   들여쓰기로 갱신한다.
6. F1-2를 명시적으로 검증하는 신규 단위 테스트를 같은 파일에 추가한다: `validate_override_key`
   (`from rag_api.config.settings import Settings, validate_override_key`)를
   `retrieval.cache.enabled`/`retrieval.cache.ttl_seconds`/`retrieval.cache.max_entries`/
   `retrieval.cache.match_mode`/`retrieval.cache.semantic_threshold` 5개 키 각각에 대해
   호출하면 `IngestValidationError("Settings key not overridable: ...")`가 발생하는지
   `pytest.raises`로 확인(5개 항목 모두 — F1-2 요구사항 그대로).
7. 실행: `uv run pytest tests/unit/test_settings.py -q`로 그린 확인.

## T2. 스키마 응답에서 `retrieval.cache.*` 오버라이드 불가 노출 확인

**대상 완료 기준**: F1-3, C2
**의존**: T1 (`CacheSettings`가 `retrieval.cache`로 존재해야 스키마에 나타남)
**관련 파일**:
- (수정) `tests/unit/test_kb_settings_api.py`

구현 방법:
1. `test_retrieval_request_scoped_fields_marked_not_overridable`(113~134행 부근)의 확인
   대상 키 목록에 `"retrieval.cache.enabled"`, `"retrieval.cache.ttl_seconds"`,
   `"retrieval.cache.max_entries"`, `"retrieval.cache.match_mode"`,
   `"retrieval.cache.semantic_threshold"` 5개를 추가한다(기존
   `retrieval.rerank.*`/`retrieval.hybrid.rrf_k`/`retrieval.similarity.min_score`와 같은
   리스트에 이어 붙인다) — `GET /api/kb/{kb_id}/settings/schema` 응답의
   `schema[key]["overridable"] is False`를 5개 항목 모두에 대해 확인(F1-3).
2. C2("검색 설정 하위 항목 중 KB별 오버라이드가 열려 있는 건 한 항목뿐" = `auto_merge`)는
   별도 신규 테스트를 추가하지 않고 이 F1-3 테스트가 5개 항목 전부 deny로 확인되는 것 자체로
   충분히 검증된다(spec.md C2 문구가 "F1-3에서 추가하는 테스트 케이스로 함께 확인" 지정).
3. 실행: `uv run pytest tests/unit/test_kb_settings_api.py -q`로 그린 확인.

## T3. `search.py`의 설정 참조 경로 갱신

**대상 완료 기준**: F3-1 (일부 — 설정 참조 자체의 정합성)
**의존**: T1
**관련 파일**:
- (수정) `src/rag_api/api/routers/search.py`
- (수정) `tests/integration/test_search_api.py`
- (수정) `tests/integration/test_search_cache_admin_api.py`

구현 방법:
1. `src/rag_api/api/routers/search.py`의 `search()` 핸들러(99행) `cache_cfg =
   settings.search_cache`를 `cache_cfg = settings.retrieval.cache`로 변경한다. 그 아래
   `cache_cfg.enabled`/`search_cache.lookup(..., cache_cfg)`/`cache_status` 로직(129~192행)은
   `cache_cfg` 변수명 자체를 그대로 참조하므로 추가 수정 불필요 — 반드시 `cache_cfg` 대입
   한 줄만 바뀌는지 확인한다(그 외 로직 변경은 비범위).
2. `tests/integration/test_search_api.py`의 `mock_settings.search_cache.enabled = False`
   (54, 98행)와 `mock_settings.search_cache.enabled = cache_enabled` /
   `mock_settings.search_cache.match_mode = match_mode`(150~151행)를 각각
   `mock_settings.retrieval.cache.enabled`/`mock_settings.retrieval.cache.match_mode`로
   갱신한다.
3. `tests/integration/test_search_cache_admin_api.py`의 `mock_settings.search_cache.enabled`
   등(92~95행)도 동일하게 `mock_settings.retrieval.cache.*`로 갱신한다.
4. 실행: `uv run pytest tests/integration/test_search_api.py tests/integration/test_search_cache_admin_api.py -q`
   로 그린 확인(리스크 1 재발 방지 — `MagicMock()`의 서브 mock 경로가 바뀌었으므로 두 경로
   모두 명시적으로 잡혀 있는지 diff로 재확인).

## T4. 배포용 설정 파일 3종 갱신

**대상 완료 기준**: F2-1, F2-2
**의존**: T1 (필드 위치가 코드에서 확정된 후 YAML을 맞춰야 함 — 순서상 함께 진행 가능하나
독립적으로 작업 가능. 다만 T1의 `Settings.model_validate` 성공 여부로 F2-2를 확인하려면
T1이 먼저 반영돼 있어야 한다)
**관련 파일**:
- (수정) `settings.yaml`
- (수정) `settings.example.yaml`
- (수정) `docker/settings.yaml`

구현 방법:
1. 세 파일 각각에서 최상위 `search_cache:` 블록(각 파일 91~120행 부근, 파일마다 줄 번호
   다름)을 통째로 잘라내 `retrieval:` 블록의 마지막 자식(`auto_merge:` 다음)으로 옮기고
   키 이름을 `cache:`로 바꾼다. 인용부호/주석/값은 그대로 유지한다(값 변경 금지 — F2-2).
   예상 결과(`settings.example.yaml` 기준):
   ```yaml
   retrieval:
     ...
     auto_merge:
       enabled: false
       merge_threshold: 0.5
     cache:
       enabled: false            # Redis에 최종 검색 응답을 캐시 (인제스트/삭제 큐 겸용 확장)
       ttl_seconds: 3600
       max_entries: 1000         # 초과 시 FIFO 축출
       match_mode: "exact"       # exact | semantic
       semantic_threshold: 0.95  # match_mode="semantic"일 때 코사인 유사도 히트 기준
   ```
2. 최상위 레벨에 `search_cache:` 키가 더 이상 남아있지 않은지 세 파일 모두 `grep -n
   '^search_cache:' settings.yaml settings.example.yaml docker/settings.yaml`로 확인한다
   (결과가 없어야 함 — F2-1).
3. F2-2 확인: T1 반영 후 `uv run python -c "from rag_api.config.settings import Settings;
   s = Settings.from_yaml(); print(s.retrieval.cache)"` 형태로(또는 기존 단위 테스트 재사용)
   각 파일을 로드해 5개 값이 이동 전과 동일한지 확인한다. `settings.yaml`은 이미
   `Settings.from_yaml()` 기본 경로이므로 T1의 `test_settings.py` 회귀 테스트가 사실상 이를
   커버하고, `settings.example.yaml`/`docker/settings.yaml`은 수동으로 위 커맨드 또는
   `yaml.safe_load` + `Settings.model_validate`로 개별 확인한다.

## T5. 데이터 스키마 문서 재검토 + 전체 회귀 확인

**대상 완료 기준**: C1, C3, F3-1(전체 통합 테스트)
**의존**: T1, T2, T3, T4 (전체 반영 후에만 의미 있는 전수 확인 task)
**관련 파일**:
- (검토만, 필요시 수정) `docs/internal/design/data-schema.md`
- 전체 테스트 스위트(수정 없음, 실행만)

구현 방법:
1. `docs/internal/design/data-schema.md` 294~297행을 다시 읽어 `search_cache` 설정 필드
   위치(top-level 여부)를 언급하는 문장이 있는지 확인한다 — design.md 조사 결과 이 구간은
   `bucket_hash`/`query_hash` 산출 로직과 모듈 경로(`query/search_cache.py`,
   `infra/search_cache.py`)만 언급하고 설정 스키마 위치는 언급하지 않는다. 실제로 그 문장
   그대로면 수정 없이 넘어간다(C1 — "변경 불필요"도 유효한 결론). 만약 다른 위치에서
   `search_cache:`를 설정 경로로 언급하는 문장을 추가로 발견하면 `retrieval.cache`로 갱신한다.
2. 캐시 관련 단위/통합 테스트 전체를 실행해 그린 확인(C3):
   `uv run pytest tests/unit/test_settings.py tests/unit/test_kb_settings_api.py
   tests/unit/test_search_cache_infra.py tests/unit/test_search_cache_query.py
   tests/unit/test_doc_state_cache_invalidation.py tests/integration/test_search_api.py
   tests/integration/test_search_cache_admin_api.py tests/unit/test_kb_api.py -q`.
3. 이 task는 T1~T4가 건드린 공유 설정 클래스(`Settings`)와 기존 프로덕션 코드
   (`search.py`)를 수정한 결과를 다루므로, design.md 리스크 1/2에서 식별한 회귀 위험이
   실제로 해소됐는지 마지막에 전체 스위트로 재확인한다: `uv run pytest -q` (프로젝트 전체
   테스트 스위트 — F3-1의 "관련 통합 테스트 전체 통과" + C3의 "전체 실행"을 함께 만족).
