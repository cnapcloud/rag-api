# US-53: 검색 응답 캐싱 — Redis 큐+캐시 겸용 확장 — Task 분리 및 구현 방법

> 담당: `designer` · spec 워크플로우 2단계 산출물(3단계 implementer 입력) · 템플릿:
> `.claude/templates/task.md`

**대상**: [design.md](design.md)

## Task 목록

| Task | 제목 | 대상 완료 기준 (AC) | 관련 파일 | 의존 |
|---|---|---|---|---|
| T1 | 검색 캐시 설정값 도입 | F1-1 | `config/settings.py`, `settings.yaml` | 없음 |
| T2 | Redis 캐시 Infra 계층(키/TTL/eviction/네임스페이스) | F1-3, F1-4, F2-1, F2-2 | `infra/search_cache.py`, `tests/conftest.py` | 없음 |
| T3 | 캐시 키 산출 + exact/semantic 판정 + 임베딩 재사용 | F3-1, F3-2, F3-5, F3-6 | `query/search_cache.py`, `query/retriever.py` | T1, T2 |
| T4 | `/api/search` 캐시 연동 + `cache_status` | F1-2, F3-3, F3-4 | `api/routers/search.py`, `tests/integration/test_search_api.py` | T1, T3 |
| T5 | 문서/KB 변경 시 자동 무효화 | F4-1, F4-2, F4-3 | `pipeline/utils/doc_state.py`, `pipeline/runner.py`, `defs/ops/ingest_ops.py`, `pipeline/steps/delete.py`, `api/routers/kb.py` | T2 |
| T6 | 캐시 수동 클리어 API | F5-1, F5-2, F5-3 | `api/routers/search.py` | T2 |
| T7 | 아키텍처 문서 갱신 | C2 | `docs/internal/architecture/README.md`, `docs/internal/design/data-schema.md` | 없음 |

## 완료 기준 커버리지

| 완료 기준 (AC) | 담당 Task |
|---|---|
| F1-1 | T1 |
| F1-2 | T4 |
| F1-3 | T2 |
| F1-4 | T2 |
| F2-1 | T2 |
| F2-2 | T2 |
| F3-1 | T3 |
| F3-2 | T3 |
| F3-3 | T4 |
| F3-4 | T4 |
| F3-5 | T3 |
| F3-6 | T3 |
| F4-1 | T5 |
| F4-2 | T5 |
| F4-3 | T5 |
| F5-1 | T6 |
| F5-2 | T6 |
| F5-3 | T6 |
| C1 | T2, T4, T5 |
| C2 | T7 |

## T1. 검색 캐시 설정값 도입

**대상 완료 기준**: F1-1
**의존**: 없음
**관련 파일**:
- (수정) `src/rag_api/config/settings.py`
- (수정) `settings.yaml`
- (수정) `tests/unit/test_settings.py`

구현 방법:
1. `config/settings.py`에 `RetrievalSettings` 근처(예: `RetrievalSettings` 바로 위 또는 아래)에
   `SearchCacheSettings(BaseModel)`을 추가한다:
   ```python
   class SearchCacheSettings(BaseModel):
       enabled: bool = False
       ttl_seconds: int = Field(default=3600, ge=1)
       max_entries: int = Field(default=1000, ge=1)
       match_mode: Literal["exact", "semantic"] = "exact"
       semantic_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
   ```
2. `Settings` 클래스에 `search_cache: SearchCacheSettings = Field(default_factory=SearchCacheSettings)`
   필드를 추가한다(다른 섹션들과 동일한 위치 스타일, 예: `retrieval` 필드 다음 줄).
3. `OVERRIDABLE_SETTINGS_PREFIXES`는 건드리지 않는다(`search_cache.`를 추가하지 않음 — KB
   오버라이드 대상 아님, design.md 참고). 아무 것도 안 해도 `validate_override_key`가 자동으로
   `search_cache.*` 키를 거부한다(allow-list 방식이므로 검증 코드 추가 불필요).
4. `settings.yaml`에 다른 섹션과 같은 스타일로 예시 블록 추가:
   ```yaml
   search_cache:
     enabled: false
     ttl_seconds: 3600
     max_entries: 1000
     match_mode: "exact"        # exact | semantic
     semantic_threshold: 0.95
   ```
5. `tests/unit/test_settings.py`에 기존 다른 섹션 테스트와 같은 패턴으로 두 테스트 추가:
   기본값 로드 확인(`Settings().search_cache.enabled is False` 등 5개 필드 전부) +
   override 값 로드 확인(YAML 문자열 또는 dict로 `Settings.model_validate(...)` 후 값 확인).

## T2. Redis 캐시 Infra 계층(키/TTL/eviction/네임스페이스)

**대상 완료 기준**: F1-3, F1-4, F2-1, F2-2
**의존**: 없음 (함수 시그니처가 `ttl_seconds`/`max_entries`를 파라미터로 받아 `Settings`에
직접 의존하지 않음 — T1과 병행 개발 가능)
**관련 파일**:
- (신규) `src/rag_api/infra/search_cache.py`
- (수정) `tests/conftest.py` — `mock_redis`/`FakeRedis` 확장
- (신규) `tests/unit/test_search_cache_infra.py`

구현 방법:
1. 키 상수 정의:
   ```python
   ENTRY_PREFIX = "rag:cache:entry"
   BUCKET_PREFIX = "rag:cache:bucket"
   KB_INDEX_PREFIX = "rag:cache:kb"
   ORDER_KEY = "rag:cache:order"
   ```
   (기존 큐 키 `rag:upload:*`/`rag:delete:*`와 겹치지 않음을 F2-1 테스트에서 문자열 비교로
   확인 — `enqueue.py`의 `UPLOAD_QUEUE_KEY` 등을 import해서 직접 대조해도 됨.)
2. 헬퍼: `_entry_key(bucket_hash, query_hash)`, `_full_key(bucket_hash, query_hash) ->
   f"{bucket_hash}:{query_hash}"`.
3. `get_entry(bucket_hash, query_hash) -> dict | None`: `GET`, 없으면 `None`, 있으면
   `json.loads`.
4. `set_entry(bucket_hash, query_hash, payload: dict, kb_ids: list[str], ttl_seconds: int,
   max_entries: int) -> None`:
   - `SETEX(entry_key, ttl_seconds, json.dumps(payload))`
   - `SADD(bucket_key, query_hash)` + `EXPIRE(bucket_key, ttl_seconds)`
   - 각 `kb_id`에 대해 `SADD(kb_index_key(kb_id), full_key)` + `EXPIRE(..., ttl_seconds)`
   - `ZADD(ORDER_KEY, {full_key: time.time()})`
   - 마지막에 `evict_if_needed(max_entries)` 호출 (F1-4).
5. `evict_if_needed(max_entries: int) -> None`: `ZCARD(ORDER_KEY) > max_entries`인 동안
   FIFO로 `ZRANGE(ORDER_KEY, 0, 0)` → 가장 오래된 `full_key` 하나를 꺼내 `ZREM`. 그 엔트리를
   `GET`해서 존재하면(`kb_ids` 파싱) 관련 `bucket`/`kb` 인덱스에서 `SREM` 후 `DEL` — 이미
   TTL로 만료되어 `GET`이 `None`이면 인덱스 정리 없이 카운트만 줄어든 것으로 보고 루프 계속
   (design.md 리스크 2의 lazy cleanup).
6. `get_bucket_query_hashes(bucket_hash) -> list[str]`: `SMEMBERS(bucket_key)`.
7. `invalidate_kb(kb_id: str) -> int`: `SMEMBERS(kb_index_key(kb_id))`로 `full_key` 목록을
   얻어 각각 entry 삭제 + bucket에서 SREM + `ORDER_KEY`에서 ZREM, 마지막에 kb 인덱스 키
   자체를 `DEL`. 삭제된 entry 수를 반환. **예외를 흡수하지 않는다** — Redis 오류는 그대로
   propagate(F5용 raw 버전, design.md 에러 모델 참고).
8. `invalidate_all() -> int`: `client.scan_iter(match="rag:cache:*")`로 전체 순회 후 일괄
   `DELETE`(배치 처리 — 너무 큰 경우 나눠서 unlink/delete). 삭제된 키 개수를 반환. 예외
   흡수하지 않음.
9. `tests/conftest.py`의 `FakeRedis`(`mock_redis` 픽스처)에 인메모리 dict/set/zset 기반으로
   `get`/`set`/`setex`(TTL 값은 별도 dict에 기록만 해도 됨, 실제 만료 시뮬레이션은 테스트에서
   필요 시 수동으로 다루거나 별도 헬퍼 제공)/`delete`/`sadd`/`srem`/`smembers`/`scan_iter`/
   `zadd`/`zrange`/`zrem`/`zcard`/`exists`/`expire`를 추가한다. 기존 `rpop`/`lpush`/`ping`
   시그니처는 그대로 두어 기존 큐 테스트(F2-2)가 영향받지 않게 한다.
10. `tests/unit/test_search_cache_infra.py`: `mock_redis` 픽스처를 사용해 `get_redis_client`를
    패치하고 위 함수들을 직접 호출해 검증. F1-3은 `setex` 호출 인자(ttl_seconds)를 스파이로
    검증하거나 FakeRedis에 TTL을 짧게 설정 후 수동으로 만료시키는 헬퍼를 둬서 검증. F1-4는
    `max_entries=2`로 설정하고 3개 저장 후 가장 오래된 것이 사라졌는지 확인. F2-1은 생성된
    키 문자열이 `rag:upload:`/`rag:delete:` 로 시작하지 않음을 확인. F2-2는 기존 큐 테스트
    (`enqueue_upload_event` 등 관련 기존 테스트)가 그대로 통과하는지 재실행 확인(신규 테스트
    추가 없이 회귀 확인 목적).

## T3. 캐시 키 산출 + exact/semantic 판정 + 임베딩 재사용

**대상 완료 기준**: F3-1, F3-2, F3-5, F3-6
**의존**: T1(설정 모양 참고), T2(infra 함수 사용)
**관련 파일**:
- (신규) `src/rag_api/query/search_cache.py`
- (수정) `src/rag_api/query/retriever.py`
- (신규) `tests/unit/test_search_cache_query.py`

구현 방법:
1. `query/retriever.py`: `_query_kb(...)`와 `query(...)` 시그니처에
   `query_embedding: list[float] | None = None`을 추가한다. `_query_kb` 내부에서:
   ```python
   if query_embedding is not None:
       from llama_index.core.schema import QueryBundle
       retrieve_input = QueryBundle(query_str=query, embedding=query_embedding)
   else:
       retrieve_input = query
   nodes = retriever.retrieve(retrieve_input)
   ```
   `query()`가 `_query_kb`를 호출하는 `run_in_executor` 라인에 `query_embedding`을 추가
   인자로 전달한다. 기본값 `None`이라 기존 호출부(`main.py`, `mcp_server/tools/search.py`,
   기존 테스트)는 수정 불필요.
2. `query/search_cache.py`에 다음을 구현:
   ```python
   def build_bucket_hash(kb_ids: list[str], effective_options: dict) -> str: ...
   def build_query_hash(bucket_hash: str, query: str) -> str: ...
   def cosine_similarity(a: list[float], b: list[float]) -> float: ...
   ```
   `effective_options`는 호출부(search.py)가 만들어 넘기는 dict — 키는 정확히
   `mode`/`top_k`/`hybrid_alpha`/`hybrid_merge_strategy`/`min_score`/`rerank_enabled`/
   `rerank_top_n` 7개(F3-1 AC의 옵션 목록과 1:1 대응). `build_bucket_hash`는
   `sorted(kb_ids)` + 이 dict를 `json.dumps(..., sort_keys=True)`로 직렬화 후
   `hashlib.sha256(...).hexdigest()` (F3-2: kb_ids 정렬로 순서 무관 보장).
3. `def lookup(query, kb_ids, effective_options, cfg: SearchCacheSettings) -> tuple[dict |
   None, list[float] | None]`:
   - `bucket_hash`/`query_hash` 계산 후 `infra_cache.get_entry`로 exact 조회. 있으면
     `(entry["response"], None)` 반환(임베딩 불필요 — retriever 호출 자체를 안 함).
   - `cfg.match_mode != "semantic"`이면 `(None, None)` 반환 — **임베딩 계산도, 버킷 스캔도
     하지 않는다**(F3-6: exact 모드에서 시맨틱 로직이 전혀 실행되지 않음).
   - semantic이면 `_get_query_embedding(query)`(아래 4번)로 임베딩을 한 번 계산 →
     `infra_cache.get_bucket_query_hashes(bucket_hash)`로 후보 나열 → 각 후보를
     `infra_cache.get_entry`로 가져와 `query_embedding` 필드와 코사인 유사도 비교 →
     `cfg.semantic_threshold` 이상 중 최댓값을 hit으로 채택(F3-5). hit 없으면
     `(None, embedding)` 반환 — 이 embedding을 호출부가 실제 검색에 재사용(재생성 금지).
   - Redis 관련 예외는 이 함수 내부에서 잡아 `logger.warning` 후 `(None, None)`으로
     폴백한다(design.md 에러 모델 — 검색 요청 경로는 fail-open).
4. `def _get_query_embedding(query: str) -> list[float]`: `from
   rag_api.pipeline.steps.embed import build_embed_model` → `build_embed_model()
   .get_query_embedding(query)`.
5. `def store(query, kb_ids, effective_options, cfg, response_dict, query_embedding=None) ->
   None`: payload 구성(design.md 데이터 모델 참고, `query_embedding`은
   `cfg.match_mode == "semantic"`일 때만 채움) 후 `infra_cache.set_entry(...)` 호출. 여기도
   Redis 예외를 흡수(`logger.warning`)해 저장 실패가 검색 응답 자체를 막지 않게 한다.
6. `def invalidate_kb(kb_id) -> int` / `def invalidate_all() -> int`: `infra_cache`의 동명
   함수를 그대로 얇게 위임(raw, 예외 전파 — F5가 사용).
7. `def invalidate_kb_best_effort(kb_id) -> int`: 위 `invalidate_kb`를 try/except로 감싸
   실패 시 `logger.warning` 후 `0` 반환(F4가 사용).
8. `tests/unit/test_search_cache_query.py`: `infra_cache`(`rag_api.infra.search_cache`)를
   패치해 순수 로직만 검증.
   - F3-1: 동일 query+kb_ids, 옵션 중 하나(`top_k` 등)만 다른 두 `effective_options`가 서로
     다른 `bucket_hash`를 만드는지.
   - F3-2: `["kb-a","kb-b"]`와 `["kb-b","kb-a"]`가 동일 `bucket_hash`를 만드는지.
   - F3-5: `build_embed_model`을 mock으로 패치해 임베딩을 고정값으로 반환시키고, 버킷에
     유사도 0.96/0.90인 두 후보를 넣어 threshold=0.95일 때 전자만 hit, 후자는 miss인지.
   - F3-6: `match_mode="exact"`일 때 `build_embed_model`(또는 `_get_query_embedding`)이
     호출되지 않음을 mock으로 확인.

## T4. `/api/search` 캐시 연동 + `cache_status`

**대상 완료 기준**: F1-2, F3-3, F3-4
**의존**: T1, T3
**관련 파일**:
- (수정) `src/rag_api/api/routers/search.py`
- (수정) `tests/integration/test_search_api.py`
- (신규 또는 기존 확장) `tests/unit/test_search.py` (선택 — 라우터 레벨 세부 케이스는
  integration 쪽에 몰아도 무방)

구현 방법:
1. `SearchMeta`에 `cache_status: Literal["hit", "miss", "disabled"]` 필드 추가.
2. `search()` 핸들러에서 기존 `_mode`/`_top_k`/`_alpha`/`_top_n`/`_min_score`/`rerank_enabled`
   계산 직후, retriever 호출 전에:
   ```python
   from rag_api.config.settings import get_settings
   from rag_api.query import search_cache

   cache_cfg = get_settings().search_cache
   effective_options = {
       "mode": _mode, "top_k": _top_k, "hybrid_alpha": _alpha,
       "hybrid_merge_strategy": req.options.hybrid.merge_strategy,
       "min_score": _min_score, "rerank_enabled": rerank_enabled, "rerank_top_n": _top_n,
   }

   query_embedding = None
   if cache_cfg.enabled:
       cached, query_embedding = search_cache.lookup(req.query, req.kb_ids, effective_options, cache_cfg)
       if cached is not None:
           cached["meta"]["cache_status"] = "hit"
           return SearchResponse(**cached)
   ```
3. retriever 호출에 `query_embedding=query_embedding` 인자를 추가.
4. 응답 조립 시 `cache_status`를 `"disabled"`(cache_cfg.enabled=False) 또는 `"miss"`(그
   외 — 위에서 hit이면 이미 return했으므로 이 지점 도달 자체가 miss 확정)로 설정.
5. `cache_cfg.enabled`이면 `SearchResponse` 생성 직후 `search_cache.store(req.query,
   req.kb_ids, effective_options, cache_cfg, response.model_dump(), query_embedding)` 호출 후
   `return response`.
6. **중요(회귀 방지, design.md 리스크 1)**: `tests/integration/test_search_api.py`의
   `test_search_returns_results`, `test_search_similarity_mode_with_min_score`가 쓰는
   `mock_settings = MagicMock()` 두 곳 모두에 `mock_settings.search_cache.enabled = False`를
   추가한다 — 안 하면 `MagicMock()`의 기본 truthy 서브 Mock 때문에 캐시 조회가 실제 Redis
   연결을 시도해 테스트가 깨진다.
7. 같은 파일에 신규 테스트 추가(캐시 활성 시나리오): `mock_settings.search_cache.enabled =
   True`, `match_mode = "exact"`로 설정하고 `rag_api.query.search_cache.lookup`/`store`를
   직접 patch해 (a) hit이면 `retriever.query`가 호출되지 않고 응답의
   `meta.cache_status == "hit"`인지(F3-3, F3-4), (b) miss면 `cache_status == "miss"`이고
   `store`가 호출됐는지, (c) `enabled=False`면 `cache_status == "disabled"`이고 `lookup`/
   `store`가 아예 호출 안 되는지(F1-2) 확인.

## T5. 문서/KB 변경 시 자동 무효화

**대상 완료 기준**: F4-1, F4-2, F4-3
**의존**: T2 (`invalidate_kb_best_effort`가 내부적으로 T2의 infra 함수를 쓰므로 T3 완료 후가
자연스럽지만, 이 task는 T3의 exact/semantic 판정 로직과는 무관하게 `invalidate_kb_best_effort`
함수 존재만 있으면 되므로 T3 전체 완료를 기다릴 필요는 없음 — 다만 실제 구현 순서상 T3에서
`query/search_cache.py` 파일 자체를 만들므로 파일 존재 여부 때문에 사실상 T3 이후 진행 권장)
**관련 파일**:
- (수정) `src/rag_api/pipeline/utils/doc_state.py`
- (수정) `src/rag_api/pipeline/runner.py`
- (수정) `src/rag_api/defs/ops/ingest_ops.py`
- (수정) `src/rag_api/pipeline/steps/delete.py`
- (수정) `src/rag_api/api/routers/kb.py`
- (신규) `tests/unit/test_doc_state_cache_invalidation.py` (또는 기존 관련 테스트 파일에 추가)

구현 방법:
1. `doc_state.py::set_indexed(doc_id, *, upsert_result, run_id="", doc_type="",
   embedding_model="", chunk_strategy="", kb_id: str = "")` — 시그니처에 `kb_id` 키워드
   인자 추가. 함수 마지막(`_pg.update_doc_fields` 이후, 로깅 이후)에:
   ```python
   if kb_id:
       from rag_api.query.search_cache import invalidate_kb_best_effort
       invalidate_kb_best_effort(kb_id)
   ```
2. `pipeline/runner.py`의 `set_indexed(...)` 호출(line ~82)에 `kb_id=kb_id,` 추가(이미
   지역 변수로 존재).
3. `defs/ops/ingest_ops.py`의 `meta_op` 안 `set_indexed(...)` 호출에
   `kb_id=valid_config["kb_id"],` 추가.
4. `pipeline/steps/delete.py::delete_doc()` — 함수 끝(soft/hard delete 로그 분기 이후,
   `kb_id`가 이미 지역 변수로 존재)에:
   ```python
   from rag_api.query.search_cache import invalidate_kb_best_effort
   invalidate_kb_best_effort(kb_id)
   ```
   (soft/hard 두 경로 모두 이 지점에 도달하므로 한 곳에만 추가하면 됨.)
5. `api/routers/kb.py::delete_kb()` — `delete_kb_meta(kb_id)` 호출 직후:
   ```python
   from rag_api.query.search_cache import invalidate_kb_best_effort
   invalidate_kb_best_effort(kb_id)
   ```
6. 테스트: `invalidate_kb_best_effort`를 mock으로 patch하고,
   - F4-1: `set_indexed(doc_id, upsert_result=..., kb_id="kb-x")` 호출 후
     `invalidate_kb_best_effort`가 `"kb-x"`로 호출됐는지.
   - F4-2: `delete_doc(doc_id)`(soft, hard 두 상태 각각) 호출 후 동일하게 확인.
   - F4-3: `client.delete("/api/kb/{kb_id}")` 통합 테스트로 호출됐는지 확인(기존
     `delete_kb` 관련 테스트가 있으면 거기 추가, 없으면 신규 최소 테스트 추가).
   - 예외를 일부러 발생시켜(mock side_effect) `invalidate_kb_best_effort`가 예외를 삼키고
     호출부(예: `delete_doc`, `delete_kb`)는 정상 완료되는지도 확인(best-effort 검증).

## T6. 캐시 수동 클리어 API

**대상 완료 기준**: F5-1, F5-2, F5-3
**의존**: T2
**관련 파일**:
- (수정) `src/rag_api/api/routers/search.py`
- (신규) `tests/integration/test_search_cache_admin_api.py`

구현 방법:
1. `search.py`에 신규 엔드포인트 추가:
   ```python
   from fastapi import Query

   @router.delete("/search/cache")
   @rest_span
   async def clear_search_cache(kb_id: str | None = Query(default=None)):
       from rag_api.query import search_cache

       if kb_id is not None:
           cleared = search_cache.invalidate_kb(kb_id)
       else:
           cleared = search_cache.invalidate_all()
       return {"status": "cleared", "kb_id": kb_id, "cleared_count": cleared}
   ```
   `search_cache.invalidate_kb`/`invalidate_all`은 T3에서 만든 raw(예외 미흡수) 버전을
   그대로 쓴다 — Redis 장애 시 `redis_lib.RedisError`가 그대로 올라가 기존 전역 핸들러가
   503으로 응답(추가 처리 불필요).
2. `kb_id`의 KB 존재 여부는 검증하지 않는다(F5-3 — 존재하지 않거나 캐시가 비어 있어도
   `cleared_count=0`으로 정상 200).
3. 테스트(`tests/integration/test_search_cache_admin_api.py`, `TestClient` 사용):
   - F5-1: 캐시에 `kb_id="kb-a"` 엔트리를 미리 넣고(`search_cache.store` 직접 호출 또는
     mock) `DELETE /api/search/cache?kb_id=kb-a` 호출 → 이후 같은 요청이 `cache_status:
     "miss"`로 바뀌는지(엔드투엔드) 또는 최소한 `cleared_count >= 1` 확인.
   - F5-2: `kb_id` 없이 `DELETE /api/search/cache` 호출 시 전체 클리어 확인(여러 kb의
     엔트리를 넣고 모두 사라지는지).
   - F5-3: 캐시가 비어있는 상태(또는 `search_cache.enabled=False` 상태)에서 두 엔드포인트
     호출 모두 200과 `cleared_count=0`을 반환하고 예외가 발생하지 않는지.

## T7. 아키텍처 문서 갱신

**대상 완료 기준**: C2
**의존**: 없음
**관련 파일**:
- (수정) `docs/internal/architecture/README.md`
- (수정) `docs/internal/design/data-schema.md`

구현 방법:
1. `docs/internal/architecture/README.md`의 "핵심 설계 원칙 → 저장소 역할 분리" 항목
   (현재 52번째 줄 부근: `Redis(인제스트·삭제 큐 전용)`)을 `Redis(인제스트·삭제 큐 + 검색
   결과 캐시 겸용)`로 갱신한다. 문장 전체 흐름이 어색하지 않게 필요하면 앞뒤 표현도 자연스럽게
   다듬는다(의미만 유지하면 됨).
2. `docs/internal/design/data-schema.md`의 `## 3. Redis — Queue only` 절:
   - 제목을 예: `## 3. Redis — Queue + Search Cache`로 변경.
   - 첫 문장(`Redis is used exclusively for the ingest and delete event queues.`)을
     "Redis is used for the ingest/delete event queues **and** the search response cache
     (US-53)." 같은 문장으로 갱신.
   - 기존 큐 키 목록 코드 블록 아래(또는 별도 하위 절)에 design.md "데이터 모델"의 Redis
     키 스킴(`rag:cache:entry:*` 등 4종)을 그대로 옮겨 문서화한다.
3. 두 파일 다 diff 리뷰로 수동 확인(C2의 완료 기준 방식이 "수동 확인"이므로 자동화 테스트는
   없음) — implementer가 최종적으로 두 파일의 변경 diff를 스스로 검토해 "Redis 큐 전용"이라는
   문구가 더 이상 남아있지 않은지 확인한다.
