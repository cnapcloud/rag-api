# US-54: 검색 캐시 설정을 retrieval 하위로 이동 + 개명 — 설계

> 담당: `designer` · spec 워크플로우 2단계 · 템플릿: `.claude/templates/design.md`

**대상**: [spec.md](spec.md)

## 아키텍처 개요

- 순수 설정 스키마 리팩터 — 컴포넌트 흐름(API → Query → Infra) 자체는 변경 없음. `Settings`
  최상위 형제 필드 `search_cache: SearchCacheSettings`를 `RetrievalSettings` 하위 필드
  `cache: CacheSettings`로 옮기고, 이를 참조하는 모든 호출부(`settings.search_cache` →
  `settings.retrieval.cache`)를 함께 고친다.
- 신규/변경 모듈: 없음(신규 모듈 없음) — `src/rag_api/config/settings.py`,
  `src/rag_api/api/routers/search.py`의 기존 클래스/참조 위치만 수정.
- 관련 설계 문서: [검색 응답 캐싱 US-53 design.md](../US-53-search-cache/design.md) (원 설계 —
  이번 spec은 그 안의 "Config" 레이어 표 항목 위치·이름만 갱신)
- 클래스명도 함께 개명한다: `SearchCacheSettings` → `CacheSettings`. 근거: `RetrievalSettings`의
  기존 하위 필드들(`hybrid: HybridSearchSettings`, `similarity: SimilaritySearchSettings`,
  `rerank: RerankerSettings`, `auto_merge: AutoMergeSettings`)이 모두 "필드명 함의 + 클래스명은
  그 섹션의 역할을 그대로 딴" 컨벤션을 따른다 — `cache: CacheSettings`가 그 패턴과 일치한다.
  (spec.md 오픈 이슈에서 designer 판단으로 위임된 사항.) `query/search_cache.py`,
  `infra/search_cache.py` 두 모듈 파일명/함수명은 그대로 둔다 — spec.md 비범위에 "동명이인
  개념을 쓰는 다른 기능 코드 변경은 대상 아님"으로 명시돼 있고, 이 두 모듈 자체는 설정
  필드가 아니라 캐시 도메인 로직 모듈이라 이번 이동과 직접 관련 없다.
- **핵심 리스크(설계 결정 필요)**: `OVERRIDABLE_SETTINGS_PREFIXES = ("ingestion.",
  "chunking.", "dedup.", "retrieval.")`에 `"retrieval."`이 이미 포함돼 있다. `cache`가
  `retrieval` 하위로 들어가면 최상위 allow-list 통과는 자동으로 되므로, 필드 단위 deny 표시
  (`json_schema_extra={"override": False}`)를 5개 필드 전부에 명시하지 않으면 F1-2/F1-3이
  깨진다(이동 전엔 `search_cache`가 애초에 allow-list에 없어 자동으로 막혔던 것과 달리,
  이동 후엔 명시적 deny가 필요해짐). `RerankerSettings`가 정확히 이 패턴(전체 deny-list)을
  이미 쓰고 있어 그대로 따른다.

## 영향 레이어 / 파일

| 레이어 | 파일 | 변경 내용 |
|---|---|---|
| Config | `src/rag_api/config/settings.py` | (수정) `SearchCacheSettings` → `CacheSettings`로 개명 + 클래스 정의를 `RetrievalSettings` 선언(`class RetrievalSettings`) 앞으로 이동, 5개 필드 전부에 `json_schema_extra={"override": False}` 추가(F1-2/F1-3). `RetrievalSettings`에 `cache: CacheSettings = Field(default_factory=CacheSettings)` 필드 추가. `Settings`에서 최상위 `search_cache: SearchCacheSettings` 필드 라인 삭제 |
| API | `src/rag_api/api/routers/search.py` | (수정) `cache_cfg = settings.search_cache` → `cache_cfg = settings.retrieval.cache` (그 외 `cache_cfg.*` 참조·`cache_status` 로직은 값 그대로라 무변경) |
| Config(문서) | `settings.yaml` | (수정) 최상위 `search_cache:` 블록을 `retrieval:` 블록의 자식 `cache:`로 이동(값 동일) |
| Config(문서) | `settings.example.yaml` | (수정) 동일하게 `retrieval.cache:`로 이동(주석 포함 값 동일) |
| Config(문서) | `docker/settings.yaml` | (수정) 동일하게 `retrieval.cache:`로 이동(값 동일) |
| 문서 | `docs/internal/design/data-schema.md` | (검토만, C1) 294~297행이 `src/rag_api/query/search_cache.py`/`infra/search_cache.py` 모듈 경로만 언급하고 설정 필드 위치(`search_cache:` 최상위 여부)는 언급하지 않는다 — 확인 결과 수정 불필요 |
| 테스트 | `tests/unit/test_settings.py` | (수정) `test_search_cache_settings_defaults`/`test_search_cache_settings_override_from_yaml`(609~640행)이 `Settings().search_cache`/YAML 최상위 `search_cache:` 키를 쓰므로 `Settings().retrieval.cache`/YAML `retrieval:\n  cache:`로 갱신. 오버라이드 거부(F1-2) 케이스 5개 필드 전부에 대한 단위 테스트 추가(`validate_override_key`가 `retrieval.cache.*` 5개 키 전부에 대해 `IngestValidationError`를 내는지) |
| 테스트 | `tests/unit/test_kb_api.py` | (검토만) `rag_api.query.search_cache.invalidate_kb*` patch 대상은 `query/search_cache.py` 모듈 참조라 이번 이동과 무관 — 무변경 |
| 테스트 | `tests/integration/test_search_api.py` | (수정) `mock_settings.search_cache.enabled = False` 등 4곳(54, 98, 150~151행)을 `mock_settings.retrieval.cache.enabled` 등으로 갱신 |
| 테스트 | `tests/integration/test_search_cache_admin_api.py` | (수정) `mock_settings.search_cache.*` 참조(92~95행)를 `mock_settings.retrieval.cache.*`로 갱신 |
| 테스트 | `tests/unit/test_search_cache_infra.py`, `tests/unit/test_search_cache_query.py`, `tests/unit/test_doc_state_cache_invalidation.py` | (검토만) `query/search_cache.py`/`infra/search_cache.py` 모듈 자체를 직접 import/patch할 뿐 `Settings.search_cache` 경로를 참조하지 않음 — 무변경 확인 |
| 테스트 | `tests/unit/test_kb_settings_schema.py` 또는 동등 스키마 테스트(존재 시) | (확인) `GET /kb/{kb_id}/settings/schema`가 `retrieval.cache.*` 5개 항목을 overridable=False로 노출하는지 F1-3 커버 케이스로 추가/확인 |

의존 방향 확인: `settings.py`(Config, 최하위 레이어에 준함) 내부 클래스 재배치이고 참조하는
쪽은 `api/routers/search.py`(API)뿐이다. API → Config 방향은 기존과 동일한 표준 하향
참조이며 역방향 참조는 생기지 않는다. `describe_overridable_settings`/
`validate_override_key`(Config 내부 함수)는 `OVERRIDABLE_SETTINGS_PREFIXES`와
`RetrievalSettings.model_fields`를 재귀 순회하는 기존 로직을 그대로 재사용하므로 `cache`
필드 추가만으로 자동 대응한다(코드 변경 불필요, F1-3 근거).

## 신규 의존성

(없음)

## API 계약

(해당 없음 — `POST /api/search`/`DELETE /api/search/cache`/`GET /kb/{kb_id}/settings*`의
요청/응답 스키마 자체는 변경 없음. 내부적으로 읽는 설정 경로만 바뀐다.)

## 데이터 모델

### `CacheSettings` (기존 `SearchCacheSettings` 개명, `config/settings.py`)

```python
class CacheSettings(BaseModel):
    """검색 응답(리랭크까지 끝난 최종 SearchResponse) 캐시 — US-53, US-54(retrieval 하위로 이동).

    retrieval.* 중 유일하게 KB별 오버라이드가 열려 있는 auto_merge와 달리, 전역 단일 정책만
    허용한다(요청 단위로 한 번만 결정되는 mode/top_k/rerank.*와 같은 이유) — 전체 deny-list.
    """

    enabled: bool = Field(default=False, json_schema_extra={"override": False})
    ttl_seconds: int = Field(
        default=3600, ge=1, description="Cache TTL (sec)", json_schema_extra={"override": False},
    )
    max_entries: int = Field(
        default=1000, ge=1, description="Max Cache Entries",
        json_schema_extra={"override": False},
    )
    match_mode: Literal["exact", "semantic"] = Field(
        default="exact", description="Cache Match Mode", json_schema_extra={"override": False},
    )
    semantic_threshold: float = Field(
        default=0.95, ge=0.0, le=1.0, description="Semantic Match Threshold",
        json_schema_extra={"override": False},
    )
```

`RetrievalSettings`에 `cache: CacheSettings = Field(default_factory=CacheSettings)` 추가.
`Settings`에서 `search_cache: SearchCacheSettings` 필드 삭제(더는 최상위에 존재하지 않음 —
F1-1).

### 배포용 설정 파일 3종 — 공통 변경 패턴

```yaml
retrieval:
  ...(기존 하위 블록들 그대로)...
  cache:
    enabled: false
    ttl_seconds: 3600
    max_entries: 1000
    match_mode: "exact"        # exact | semantic
    semantic_threshold: 0.95
```

세 파일 각각 기존 최상위 `search_cache:` 블록(주석 포함)을 그대로 `retrieval:` 블록 자식으로
옮긴다 — 값/주석 내용 변경 없음(F2-1/F2-2).

## 에러 모델

(해당 없음 — 새 예외 클래스 없음. 기존 `IngestValidationError("Settings key not overridable: ...")`
가 `retrieval.cache.*` 5개 키에 대해서도 그대로 발생하는지만 F1-2/F1-3에서 확인한다.)

## 로깅

(해당 없음 — 이번 변경으로 로그 메시지/시점 변경 없음. US-53에서 이미 확정된
`Search cache hit/miss/stored/evicted/invalidated` 로그 문구는 그대로 유지된다.)

## NFR

(해당 없음 — spec.md에 NFR 없음. 순수 설정 위치 리팩터라 런타임 동작·성능에 영향 없음.)

## 리스크 & 롤백

- 리스크 1(핵심): `retrieval.`이 이미 오버라이드 allow-list에 있어, `cache`의 5개 필드에
  `json_schema_extra={"override": False}`를 빠짐없이 붙이지 않으면 이동 전엔 없던 "KB별
  캐시 설정 오버라이드"가 조용히 열려버린다(F1-2/F1-3 회귀) — 완화: task.md에서 5개 필드
  전부에 대한 개별 오버라이드 거부 테스트를 명시(전체 통과 없이는 완료로 보지 않음).
- 리스크 2: `settings.search_cache`를 참조하는 호출부를 누락하면 `AttributeError`가 난다 —
  완화: 코드베이스 전체에서 `search_cache` grep 결과 프로덕션 코드 참조는
  `config/settings.py`(정의)와 `api/routers/search.py`(단 1곳, `cache_cfg = settings.search_cache`)
  뿐임을 이미 확인했다(위 "영향 레이어/파일" 표). 그 외 매치는 전부 모듈명(`query/search_cache.py`,
  `infra/search_cache.py`) 또는 테스트의 mock 속성 경로라 별도 처리.
- 리스크 3: 세 YAML 파일 중 하나라도 들여쓰기를 놓치면 `retrieval:` 블록이 아니라 별도
  top-level 키로 잘못 남을 수 있다 — 완화: F2-1이 "diff로 top-level `search_cache:` 부재 +
  `retrieval.cache:` 존재"를 수동 확인하도록 명시돼 있어 task.md에서 세 파일 모두 diff 확인을
  구현 방법에 포함한다.
- 롤백: 커밋 revert로 충분하다. 스키마 마이그레이션/Redis 키 스킴 변경 없음(Redis 키는
  여전히 `rag:cache:*` prefix로 설정 필드 위치와 무관), 값 자체는 바뀌지 않으므로 되돌려도
  동작에 영향 없음.

## 오픈 이슈

- (없음 — spec.md 오픈 이슈였던 "내부 구현 요소 개명 여부"는 위 아키텍처 개요에서
  `CacheSettings`로 개명하기로 결정 완료.)

## 설계 검토 체크

- [x] `architecture` 스킬 기준 레이어/의존성 방향 확인 완료 (역방향 참조 없음 — Config
      내부 재배치 + API의 표준 하향 참조 1곳뿐)
- [x] spec.md의 모든 완료 기준(AC)이 이 설계로 커버됨 (task.md 완료 기준 커버리지 표 참고)
- [x] 오픈 이슈 없음
