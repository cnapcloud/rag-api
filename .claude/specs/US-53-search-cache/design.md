# US-53: 검색 응답 캐싱 — Redis 큐+캐시 겸용 확장 — 설계

> 담당: `designer` · spec 워크플로우 2단계 · 템플릿: `.claude/templates/design.md`

**대상**: [spec.md](spec.md)

## 아키텍처 개요

- 컴포넌트 흐름(캐시 미스): `API(search.py)` → `Query(query/search_cache.py)`(캐시 판정) →
  `Query(query/retriever.py)`(실제 검색·리랭크) → `Infra(infra/search_cache.py)`(Redis 저장)
- 컴포넌트 흐름(캐시 히트): `API(search.py)` → `Query(query/search_cache.py)` →
  `Infra(infra/search_cache.py)`(Redis 조회) → 즉시 반환(`retriever`/`reranker` 미호출)
- 레이어 분리 원칙: Redis I/O(키 스킴, TTL, eviction, SCAN)는 `infra/search_cache.py`에만 두고,
  캐시 키 산출·시맨틱 유사도 비교·임베딩 재사용 오케스트레이션 같은 "검색 도메인 로직"은
  `query/search_cache.py`에 둔다. API 레이어(`search.py`)는 두 모듈의 공개 함수만 호출한다.
- 신규 모듈:
  - `src/rag_api/infra/search_cache.py` (신규) — Redis 키 스킴/CRUD/eviction/무효화 primitive
  - `src/rag_api/query/search_cache.py` (신규) — 캐시 키(exact/semantic) 산출, hit/miss 판정,
    저장, 무효화(safe/raw 두 버전)
- 변경 모듈: `config/settings.py`(설정 추가), `settings.yaml`(문서화),
  `api/routers/search.py`(캐시 연동 + `SearchMeta.cache_status` + 수동 클리어 API),
  `query/retriever.py`(사전 계산된 질의 임베딩 재사용), `pipeline/utils/doc_state.py`,
  `pipeline/runner.py`, `defs/ops/ingest_ops.py`, `pipeline/steps/delete.py`,
  `api/routers/kb.py`(F4 자동 무효화 훅), `docs/internal/architecture/README.md`,
  `docs/internal/design/data-schema.md`(C2)
- 범위 경계(중요): 캐싱은 `POST /api/search`(FastAPI 라우터)에만 적용한다. CLI(`rag-api search`,
  `main.py`)와 MCP 도구(`mcp_server/tools/search.py`)는 `query/retriever.query()`를 직접
  호출하며 이번 US 범위 밖이므로 캐시를 거치지 않는다(spec.md 목적 문구가 "`POST /api/search`의
  최종 응답"으로 명시적으로 한정). `retriever.query()`에 추가하는 `query_embedding` 파라미터는
  기본값 `None`이라 이 두 호출부는 코드 변경 없이 기존 동작을 그대로 유지한다.

### 시맨틱 매칭 위치 결정 (오픈 이슈였던 사항)

전용 Qdrant 컬렉션을 만들지 않고, Redis에 저장된 캐시 엔트리의 질의 임베딩끼리 **Python
브루트포스 코사인 유사도 비교**로 구현한다. 근거: `max_entries` 기본 1000이 전역 상한이고,
시맨틱 비교는 "같은 kb_ids+검색옵션 버킷" 내부로만 좁혀지므로 한 버킷의 후보 수는 최대
1000을 절대 넘지 않는다(대개 훨씬 작음) — 이 규모에서 벡터 DB 별도 운영(인덱스 동기화, TTL과
컬렉션 정리 시점 불일치 위험)보다 단순 선형 스캔이 지연시간·운영 복잡도 모두에서 유리하다.
`match_mode=semantic`은 기본 비활성 옵션이라 이 선형 스캔 비용은 옵트인 사용자에게만 발생한다.

### 질의 임베딩 재사용 메커니즘 (F3-5 핵심)

LlamaIndex 리트리버는 `retriever.retrieve(query_bundle)`에 `QueryBundle(query_str=...,
embedding=[...])`을 넘기면 `embedding`이 이미 채워진 경우 내부적으로 재임베딩하지 않는다
(`llama_index/core/indices/vector_store/retrievers/retriever.py`의
`query_bundle.embedding is None` 분기 — 이 리포의 설치된 llama-index-core 버전에서 확인 완료).
이를 이용해:

1. `match_mode=exact`이거나 exact 캐시가 hit이면 임베딩을 아예 계산하지 않는다.
2. `match_mode=semantic`이고 exact 캐시가 miss이면, `query/search_cache.py`가
   `build_embed_model().get_query_embedding(query)`로 질의 임베딩을 **한 번만** 계산해
   (a) 캐시 버킷 내 기존 엔트리들과의 코사인 유사도 비교, (b) semantic도 miss일 경우
   `retriever.query(..., query_embedding=embedding)`로 그대로 전달 — 두 용도 모두 같은
   임베딩을 재사용하고 별도로 재생성하지 않는다.
3. `retriever.py`의 `_query_kb`는 `query_embedding`이 주어지면 `QueryBundle(query_str=query,
   embedding=query_embedding)`을, 아니면 기존처럼 문자열 그대로 `retriever.retrieve()`에
   넘긴다 — 캐시 비활성/`exact` 모드에서는 동작이 기존과 100% 동일하다.

## 영향 레이어 / 파일

| 레이어 | 파일 | 변경 내용 |
|---|---|---|
| Config | `src/rag_api/config/settings.py` | (수정) `SearchCacheSettings`(enabled/ttl_seconds/max_entries/match_mode/semantic_threshold) 추가, `Settings.search_cache` 필드 추가. `OVERRIDABLE_SETTINGS_PREFIXES`에는 넣지 않음(KB 오버라이드 대상 아님 — spec.md에 언급 없음) |
| Config(문서) | `settings.yaml` | (수정) `search_cache:` 블록 추가(기본값 명시, 오버라이드 예시) |
| Infra | `src/rag_api/infra/search_cache.py` | (신규) Redis 키 스킴(`rag:cache:entry:*`/`rag:cache:bucket:*`/`rag:cache:kb:*`/`rag:cache:order`), `get_entry`/`set_entry`/`get_bucket_query_hashes`/`evict_if_needed`/`invalidate_kb`/`invalidate_all` |
| Query | `src/rag_api/query/search_cache.py` | (신규) 캐시 키(버킷/쿼리 해시) 산출, exact/semantic `lookup()`, `store()`, `cosine_similarity()`, `invalidate_kb()`/`invalidate_all()`(raw, 예외 전파 — F5용), `invalidate_kb_best_effort()`(예외 흡수 — F4용) |
| Query | `src/rag_api/query/retriever.py` | (수정) `query()`/`_query_kb()`에 `query_embedding: list[float] \| None = None` 파라미터 추가, 주어지면 `QueryBundle`로 리트리버에 전달 |
| API | `src/rag_api/api/routers/search.py` | (수정) `SearchMeta.cache_status` 필드 추가, `search()` 핸들러에 캐시 조회/저장 연동, 신규 `DELETE /search/cache` 엔드포인트(F5) |
| Pipeline | `src/rag_api/pipeline/utils/doc_state.py` | (수정) `set_indexed(..., kb_id: str = "")` — indexed 전이 시 `invalidate_kb_best_effort(kb_id)` 호출(F4-1) |
| Pipeline | `src/rag_api/pipeline/runner.py` | (수정) `set_indexed(...)` 호출에 `kb_id=kb_id` 추가 |
| Pipeline | `src/rag_api/defs/ops/ingest_ops.py` | (수정) `meta_op`의 `set_indexed(...)` 호출에 `kb_id=valid_config["kb_id"]` 추가 |
| Pipeline | `src/rag_api/pipeline/steps/delete.py` | (수정) `delete_doc()` 종료 시점(soft/hard 공통 경로)에 `invalidate_kb_best_effort(kb_id)` 호출(F4-2) |
| API | `src/rag_api/api/routers/kb.py` | (수정) `delete_kb()`에서 `delete_kb_meta(kb_id)` 이후 `invalidate_kb_best_effort(kb_id)` 호출(F4-3) |
| 문서 | `docs/internal/architecture/README.md` | (수정) "저장소 역할 분리" 문구 갱신(C2) |
| 문서 | `docs/internal/design/data-schema.md` | (수정) §3 제목/서술 갱신 + 캐시 키 스킴 추가(C2) |
| 테스트 | `tests/conftest.py` | (수정) `mock_redis`(`FakeRedis`)에 `get`/`set`/`setex`/`delete`/`sadd`/`srem`/`smembers`/`scan_iter`/`zadd`/`zrange`/`zrem`/`zcard`/`exists` 추가 — 큐 전용이던 기존 fixture를 캐시 테스트에도 재사용 가능하게 확장(기존 `rpop`/`lpush`/`ping` 시그니처는 그대로 유지, 회귀 없음) |
| 테스트 | `tests/unit/test_settings.py` | (수정) `SearchCacheSettings` 기본값/오버라이드 테스트 추가 |
| 테스트 | `tests/unit/test_search_cache_infra.py` | (신규) Infra 레이어 단위 테스트 |
| 테스트 | `tests/unit/test_search_cache_query.py` | (신규) Query 레이어 단위 테스트(exact/semantic 판정, 임베딩 재사용 mock 검증) |
| 테스트 | `tests/integration/test_search_api.py` | (수정) 기존 `mock_settings`에 `mock_settings.search_cache.enabled = False` 명시 추가(아래 리스크 참고) + 캐시 hit/miss/cache_status 통합 테스트 추가 |
| 테스트 | `tests/integration/test_search_cache_admin_api.py` | (신규) F5 클리어 API 통합 테스트 |

의존 방향 확인: API → Query → Infra만 존재하고 역방향 참조 없음. `pipeline/utils/doc_state.py`
와 `pipeline/steps/delete.py`(Pipeline 레이어)가 `query/search_cache.py`(Query 레이어)를
호출하는 것은 레이어표상 `Pipeline`이 `Query`보다 상위가 아니라 같은 계층(둘 다 API 하위,
Infra 상위)으로 취급되는 기존 코드베이스 관례와 일치한다 — 예컨대 기존
`query/retriever.py::_query_kb`도 `pipeline/utils/sparse.py`(Pipeline)를 이미 참조하는 등
Pipeline↔Query 상호 참조가 기존에도 존재하며, 이번 변경은 그 방향을 뒤집지 않는다(둘 다
Infra만을 최종적으로 향함). `api/routers/kb.py`(API)가 `query/search_cache.py`(Query)를
호출하는 것은 표준 하향 참조로 문제없다.

## API 계약

```
POST /api/search  (기존 — 응답 스키마만 확장)
  성공: 200
    {
      "query": "...",
      "results": [...],
      "meta": {
        ...(기존 필드),
        "cache_status": "hit" | "miss" | "disabled"
      }
    }
  실패: 기존과 동일(422 kb_ids 누락 등) — 캐시 로직 자체는 Redis 오류를 삼키고 항상
        실제 검색으로 폴백하므로(아래 에러 모델 참고) 캐시 도입으로 인한 신규 실패 코드 없음.

DELETE /api/search/cache?kb_id=<optional>
  성공: 200 {"status": "cleared", "kb_id": "<kb_id 또는 null>", "cleared_count": <int>}
        — kb_id 생략 시 전체 캐시 클리어(F5-2), 지정 시 해당 kb_id 캐시만 클리어(F5-1).
          캐시가 비활성이거나 대상 엔트리가 0개여도 정상 200(F5-3) — kb_id 존재 여부는
          검증하지 않는다(존재하지 않는 kb_id도 cleared_count=0으로 정상 처리).
  실패: 503 {"detail": "..."} — Redis 자체가 응답하지 않는 등 실제 인프라 장애 시
        (기존 `redis_lib.RedisError` 전역 핸들러가 이미 503으로 매핑, `api/app.py` 참고).
        이 경로는 "F5는 운영자가 명시적으로 호출하는 API이므로 실패를 숨기지 않는다"는
        설계 결정에 따라 의도적으로 예외를 흡수하지 않는다(F4 자동 무효화 훅과의 차이,
        아래 에러 모델 참고).
```

## 데이터 모델

### Redis 키 스킴 (큐와 분리된 별도 prefix, 같은 DB index 재사용)

```
rag:cache:entry:{bucket_hash}:{query_hash}   String(JSON), TTL=ttl_seconds
  {
    "query": "<원문 질의>",
    "kb_ids": ["<정렬된 kb_id 목록>"],
    "response": { ... SearchResponse.model_dump() 그대로(cache_status 값은 저장 시 의미 없음,
                  hit 시 항상 "hit"으로 덮어써서 반환) ... },
    "query_embedding": [float, ...] | null,   -- match_mode=semantic일 때만 채움
    "created_at": <epoch float>
  }
rag:cache:bucket:{bucket_hash}                Set<query_hash>        -- semantic 스캔용
rag:cache:kb:{kb_id}                          Set<"{bucket_hash}:{query_hash}">  -- F4/F5 무효화용
rag:cache:order                               ZSet<"{bucket_hash}:{query_hash}", score=epoch>  -- FIFO eviction
```

- `bucket_hash = sha256(json.dumps({"kb_ids": sorted(kb_ids), "mode":, "top_k":,
  "hybrid_alpha":, "hybrid_merge_strategy":, "min_score":, "rerank_enabled":,
  "rerank_top_n":}, sort_keys=True))` — F3-1(옵션 조합 전체 일치)·F3-2(kb_ids 순서 무관)를
  이 해시 하나로 만족시킨다.
- `query_hash = sha256(f"{bucket_hash}|{query}")` — exact 매칭 키.
- 기존 큐 키(`rag:upload:*`, `rag:delete:*`)와 겹치지 않음(F2-1) — 같은 Redis DB index(0)를
  재사용하되 prefix(`rag:cache:`)만 별도로 둔다. 별도 DB index 대신 prefix 분리를 택한
  이유: 새 커넥션 풀/설정(`redis.cache_db` 등) 없이 기존 `get_redis_client()` 싱글턴을 그대로
  재사용할 수 있어 구현·롤백 모두 단순함.
- 인덱스 구조(`bucket`/`kb`/`order`)에도 엔트리와 동일한 `ttl_seconds`로 EXPIRE를 갱신한다
  (쓰기 시마다) — TTL로 자연 만료된 엔트리의 참조가 인덱스에 무한정 남지 않도록 하는
  근사적 정리(완벽한 정합성은 아니며 아래 리스크 참고).

### `SearchMeta` 필드 추가

`cache_status: Literal["hit", "miss", "disabled"]` — `search_cache.enabled=false`면
항상 `"disabled"`(F1-2), 활성 상태에서 실제 hit/miss 여부를 그대로 반영(F3-4).

### `SearchCacheSettings` (신규, `config/settings.py`)

```python
class SearchCacheSettings(BaseModel):
    enabled: bool = False
    ttl_seconds: int = Field(default=3600, ge=1)
    max_entries: int = Field(default=1000, ge=1)
    match_mode: Literal["exact", "semantic"] = "exact"
    semantic_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
```

`Settings.search_cache: SearchCacheSettings = Field(default_factory=SearchCacheSettings)` 추가.
`OVERRIDABLE_SETTINGS_PREFIXES`에는 포함하지 않는다 — spec.md에 KB별 캐시 설정 오버라이드
요구가 없고, 전역 단일 정책으로 충분하다.

## 에러 모델

새 `RAGError` 하위 클래스는 추가하지 않는다. Redis 장애 시 두 가지 다른 정책을 의도적으로
둔다:

- **검색 요청 경로(F1~F3, `search()` 핸들러)**: `query/search_cache.py`의 `lookup()`/`store()`는
  `redis_lib.RedisError`(및 JSON 역직렬화 실패 등 예기치 못한 예외)를 내부에서 잡아
  `logger.warning`으로만 남기고 "캐시 미스처럼" 폴백한다 — 캐시는 최적화 계층이므로 Redis
  장애가 검색 자체를 막아서는 안 된다(기존 `_filter_orphaned_chunks`의 best-effort 패턴과
  동일한 철학).
- **F4 자동 무효화 훅(`doc_state.set_indexed`/`delete.py`/`kb.py::delete_kb`)**: 반드시
  `invalidate_kb_best_effort()`를 사용한다 — Redis가 죽어 있다고 해서 인제스트 완료·문서
  삭제·KB 삭제라는 이미 커밋된 작업이 실패로 보고되면 안 된다.
- **F5 수동 클리어 API**: `query/search_cache.py`의 raw `invalidate_kb()`/`invalidate_all()`을
  그대로 호출해 Redis 예외를 삼키지 않는다 — 운영자가 명시적으로 요청한 클리어 동작이므로
  실패를 숨기면 안 되고, 기존 `redis_lib.RedisError → 503` 전역 핸들러(`api/app.py`)에 그대로
  위임한다.

## 로깅

- 캐시 hit/miss: `logger.info("Search cache hit: mode=%s bucket=%s", match_mode, bucket_hash[:8])`
  / 동일 패턴으로 miss.
- 저장/eviction: `logger.info("Search cache stored: bucket=%s ttl=%d", ...)`,
  eviction 발생 시 `logger.info("Search cache evicted: count=%d max_entries=%d", ...)`.
- 무효화: `logger.info("Search cache invalidated: kb_id=%s cleared=%d", kb_id, count)`
  (F4/F5 공통), best-effort 경로에서 예외를 삼킬 때만 `logger.warning`.
- 모두 영어 메시지(하드 룰), 이모지 없음.

## NFR

(spec.md에 명시된 NFR 없음 — 성능/지연시간 수치 목표는 요구되지 않았다. 다만 설계상 참고:
시맨틱 매칭의 선형 스캔은 버킷당 최대 `max_entries`(기본 1000)로 상한이 있고, 캐시 히트
경로는 임베딩·검색·리랭크(외부 Jina API 호출 포함)를 모두 생략하므로 spec.md 목적("레이턴시,
외부 리랭크 API 호출 비용 절감")에 부합한다.)

## 리스크 & 롤백

- **리스크 1 (회귀, 중요)**: `tests/integration/test_search_api.py`의 기존 테스트들이
  `mock_settings = MagicMock()`을 쓰는데, `search.py`가 새로 `get_settings().search_cache.enabled`를
  읽는다. `MagicMock()`은 명시하지 않은 하위 속성을 기본적으로 truthy한 서브 Mock으로
  반환하므로, `mock_settings.search_cache.enabled`를 명시적으로 `False`로 설정하지 않으면
  캐시 조회 로직이 실행되어 테스트 중 실제 Redis 연결을 시도해 기존 테스트가 깨진다 — 완화:
  T4에서 해당 테스트 파일의 모든 `mock_settings`에 `mock_settings.search_cache.enabled = False`를
  반드시 추가한다(task.md T4에 명시).
- **리스크 2**: 인덱스 자료구조(`bucket`/`kb`/`order`)가 TTL로 자연 만료된 엔트리를 계속
  참조하는 "고아 참조"가 생길 수 있다 — 완화: (a) eviction 시점에 존재하지 않는 엔트리를
  만나면 그 자리에서 lazy하게 인덱스에서도 제거, (b) 인덱스 자료구조에도 엔트리와 동일한
  TTL을 갱신 적용해 결국 함께 만료되게 한다. 완벽한 실시간 정합성은 아니지만 캐시라는
  용도상 허용 가능한 근사치다.
- **리스크 3**: `match_mode=semantic`은 오탐(의도가 다른 질문이 같은 캐시를 반환) 가능성이
  있다 — 완화: 기본값 `enabled=false`+`match_mode=exact`로 옵트인 전용이며, 기본
  `semantic_threshold=0.95`(보수적)로 spec.md에서 이미 확정. 추가 완화가 필요하면(예: 임계값
  튜닝 UI) 별도 US.
- **리스크 4**: `set_indexed()` 시그니처에 `kb_id` 파라미터가 추가되므로 호출부
  (`runner.py`, `ingest_ops.py`) 양쪽을 함께 수정해야 한다 — 누락 시 F4-1이 조용히
  동작하지 않는다(예외는 안 나지만 무효화가 안 됨). 완화: task.md T5에서 두 호출부를 모두
  명시.
- **롤백**: 커밋 revert로 충분하다. 스키마 마이그레이션 없음(Postgres 변경 없음), Redis는
  새 prefix(`rag:cache:*`)만 추가하므로 되돌려도 기존 큐 키에 영향 없음. `settings.yaml`에
  추가한 `search_cache:` 블록도 기본값과 동일해 제거해도 동작에 영향 없음.

## 오픈 이슈

- `src/rag_api/infra/CLAUDE.md`의 "ETag 캐시" 키 컨벤션 불일치는 spec.md 비범위로 이미 확정된
  기존 이슈이며, 이번 US에서도 그 파일을 건드리지 않는다(별도 정리 필요, US-53 범위 아님).
- 인덱스 자료구조의 TTL 동기화(리스크 2)는 "결국 수렴하는 근사치"로 설계했다 — 완벽한
  즉시 정합성이 필요하다는 후속 요구가 생기면 별도 검토가 필요하다(이번 US 범위에서는
  spec.md의 어떤 AC도 이 수준의 정합성을 요구하지 않는다).

## 설계 검토 체크

- [x] `architecture` 스킬 기준 레이어/의존성 방향 확인 완료 (역방향 참조 없음 — 위 "영향
      레이어/파일" 표 아래 의존 방향 설명 참고)
- [x] spec.md의 모든 완료 기준(AC)이 이 설계로 커버됨 (task.md 완료 기준 커버리지 표에서
      F1-1~C2까지 전량 매핑 확인)
- [x] 오픈 이슈 없음이 아니라 위 2건이 있으나 모두 "이번 US 범위 밖으로 이미 확정됨" 또는
      "허용 가능한 근사치로 설계에 반영됨" — 구현을 막는 블로킹 이슈 아님
