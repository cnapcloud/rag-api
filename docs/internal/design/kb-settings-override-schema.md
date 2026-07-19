# KB 설정 오버라이드 — 필드 스키마 설계

> 요건: 없음 — 순수 기술 설계 문서. override 방식(리졸버·저장 스키마·REST API·파서 레지스트리
> 재설계)은 [`kb-settings-override.md`](kb-settings-override.md)(이하 base 문서)를 참조한다.
> 이 문서는 base 문서가 다루지 못했던 `Settings`의 개별 필드 자체(값 검증/설명/override 허용
> 여부)를 처리한다. **base 문서는 이 설계로 갱신하지 않는다.**

## 1. 배경 — 근본 목적은 `Settings` 필드 자체의 결함

**이 문서의 근본 목적은 rag-admin UI가 아니라 `Settings` 모델 자체다.** base 문서 §9.1의
저장 시점 검증은 타입만 걸러낼 뿐, 개별 필드에 대한 값 검증(min/max)·설명(description)·
override 허용 여부(allow/deny) 세 가지가 필드 선언 옆에 정식으로 존재한 적이 없다:

1. **값 검증 부재**: `jaccard_threshold`에 `-1`이나 `5.0`처럼 타입은 맞지만 의미상 말이 안 되는
   값을 override로 넣어도 `type(base)(**merged)` 재검증을 그대로 통과한다(§2).
2. **description 부재**: 일부 필드는 Python 주석으로만 설명이 달려 있고, 이 주석은 런타임에
   전혀 읽히지 않는다(§4.2).
3. **override 허용 여부가 코드에 흩어짐**: `EXCLUDED_OVERRIDE_KEYS` frozenset(base 문서 §5)이
   필드 선언과 분리된 별도 문자열 목록이라, 새 필드를 추가할 때 배제 처리를 깜빡하면 조용히
   오버라이드 가능해지는 드리프트 위험이 있다(§4).

이 세 가지를 필드 선언 옆(`Field(ge=, le=, description=..., json_schema_extra=...)`)으로
옮겨 `Settings` 모델 자체를 고치는 것이 이 문서의 본 목적이다(§2·§4·§4.1·§4.2). rag-admin이
KB Settings Override 화면(`kb-settings-override-ui.md`)을 설계하며 "필드 목록을 하드코딩하지
않고 동적으로 폼을 그리려면 스키마 API가 필요하다"는 요구가 이 작업을 촉발한 계기이긴 했지만,
그건 결과일 뿐이다 — `Settings` 모델에 값 검증/description/override 허용 여부가 필드 단위로
정식으로 존재하게 되면, 그 정보를 그대로 순회해 직렬화하는 `/settings/schema` 엔드포인트(§5)는
자연히 따라 나온다. 즉 rag-admin의 "동적 UI 구성" 문제는 별도로 푼 게 아니라, `Settings`의
기존 설계 결함(위 세 가지)을 해소하면서 부수적으로 함께 풀린 것이다.

## 2. 전체 속성 표 — min/max · enum · override 적용안

`rag_api/config/settings.py`의 `Settings` 전체 그룹(§2.1)과, `resolve_settings()`가 실제로
병합 대상으로 삼는 rag-ent-api 확장 필드(`rag_ent/config/settings.py`, §2.2)를 모두 포함한다.
override 열은 base 문서 §9.1의 접두사 allow-list(`ingestion.`/`chunking.`/`dedup.`)를 통과하는
그룹만 "가능/배제" 판정이 의미가 있고, 그 밖의 그룹(server/s3/redis/... )은 allow-list 자체에
걸려 **구조적으로 배제**다 — §2.3에 그룹 단위로만 정리한다.

min/max가 있는 필드는 전부 Pydantic `Field(ge=, le=)`로 구현 가능한 단순 range다. cross-field
제약(다른 필드 값에 의존하는 범위)은 이 표에 "cross-field" 표시만 하고 §3에서 별도로 다룬다.

### 2.1 ingestion / chunking / dedup — override 대상 그룹 (rag-api 자체 필드)

| dot-key | 타입 | 기본값 | enum | min | max | override | description(제안) | 비고 |
|---|---|---|---|---|---|---|---|---|
| `ingestion.max_file_size_mb` | int | 200 | - | 1 | 1024 | 가능 | Max File Size (MB) | 하한은 0/음수 방지, 상한(1GB)은 임의 가드레일 |
| `ingestion.min_content_chars` | int | 200 | - | 0 | 5000 | 가능 | Min Content Chars | 0 = 검사 비활성화로 해석 가능. 상한은 "이 값 이상이면 사실상 모든 문서가 거부"되는 임의 가드레일 |
| `ingestion.html_extraction_policy` | str (`Literal`) | `lenient` | `strict`/`lenient`/`balanced` | - | - | 가능 | HTML Extraction Policy | 이미 `Literal` — Pydantic이 값 검증을 자동으로 함, 별도 range 불필요 |
| `ingestion.parser_plugins` | `list[str]` | `[]` | - | - | - | **배제** | Parser Plugins | base 문서 §5 — 배포 타임 모듈 존재 여부, KB별 분기 시 last-writer-wins 충돌 |
| `chunking.strategy` | str (plain) | `recursive` | `recursive`/`semantic` | - | - | 가능 | Chunking Strategy | **현재 `Literal` 미선언** — `ChunkingSettings.strategy: str`는 어떤 문자열이든 통과시킨다. 실제로 유효한 값은 `pipeline/steps/chunk.py`의 `ChunkStrategy = Literal["recursive", "semantic"]`(2개뿐 — `document_aware`는 US-03 대기 중, 아직 미구현)뿐이고, 이 필드는 그 타입을 재사용하지 않는다. §4.1에서 `ChunkStrategy` 재사용으로 승격하기로 함 |
| `chunking.chunk_size` | int | 1024 | - | 64 | 8192 | 가능 | Chunk Size | cross-field: `chunk_overlap < chunk_size`(§3) |
| `chunking.chunk_overlap` | int | 128 | - | 0 | 8191 | 가능 | Chunk Overlap | cross-field: `chunk_overlap < chunk_size`(§3) |
| `chunking.min_chunk_chars` | int | 30 | - | 1 | 2000 | 가능 | Min Chunk Chars | 상한은 `chunk_size` 대비 상식적 가드레일 |
| `chunking.semantic_threshold` | float | 0.8 | - | 0.0 | 1.0 | 가능 | Semantic Threshold | 코사인 유사도류 threshold로 추정 |
| `chunking.code_chunk_lines` | int | 40 | - | 5 | 500 | 가능 | Code Chunk Lines | cross-field: `code_chunk_lines_overlap < code_chunk_lines`(§3) |
| `chunking.code_chunk_lines_overlap` | int | 5 | - | 0 | 499 | 가능 | Code Chunk Lines Overlap | cross-field: 위와 동일 |
| `dedup.enabled` | bool | `true` | - | - | - | 가능 | Dedup Enabled | bool은 range 없음 |
| `dedup.chunk_compare.chunk_match_threshold` | float | 0.50 | - | 0.0 | 1.0 | 가능 | Chunk Match Threshold | |
| `dedup.chunk_compare.body_identical_threshold` | float | 0.95 | - | 0.0 | 1.0 | 가능 | Body Identical Threshold | cross-field: `body_similar_threshold <= body_identical_threshold`(§3) |
| `dedup.chunk_compare.body_similar_threshold` | float | 0.75 | - | 0.0 | 1.0 | 가능 | Body Similar Threshold | cross-field: 위와 동일 |
| `dedup.chunk_compare.compare_all_candidates` | bool | `false` | - | - | - | 가능 | Compare All Candidates | bool은 range 없음 |
| `dedup.minhash.jaccard_threshold` | float | 0.65 | - | 0.0 | 1.0 | 가능 | Jaccard Threshold | |
| `dedup.minhash.title_fuzzy_threshold` | float | 0.85 | - | 0.0 | 1.0 | 가능 | Title Fuzzy Threshold | |
| `dedup.minhash.title_only_min_jaccard_floor` | float | 0.25 | - | 0.0 | 1.0 | 가능 | Title-Only Min Jaccard Floor | `jaccard_threshold`와의 대소 관계가 cross-field 후보로 보이나 확정하지 않음 — §3 참고 |
| `dedup.minhash.user_words_path` | str | `""` | - | - | - | **배제** | User Words Path | base 문서 §5 — Kiwi 토크나이저 프로세스 전역 싱글턴 |
| `dedup.simhash.hamming_identical_threshold` | int | 3 | - | 0 | 19 (구현 시 le=19 sanity cap 추가) / `/settings/schema` 응답 `max`는 여전히 `simhash_bits` 기준 동적값 | 가능 | Hamming Identical Threshold | 구현 시 반영(2026-07-19): Field 자체엔 정적 `le=19`를 둬 저장 시점에 무의미하게 큰 값을 막고, 표시용 `max`는 원래 설계대로 그 배포의 `simhash_bits`로 동적 계산(§5 예외 항목 그대로 유지) |
| `dedup.simhash.hamming_similar_threshold` | int | 10 | - | 0 | 19 (위와 동일) | 가능 | Hamming Similar Threshold | cross-field: `hamming_identical_threshold <= hamming_similar_threshold`(§3) + 위와 동일한 `simhash_bits` 종속 및 le=19 cap |
| `dedup.simhash.ngram` | int | 3 | - | - | - | **배제** | N-gram Size | base 문서 §5 — 기존 `simhash_bands` 지문과 계산 방식 불일치 위험 |
| `dedup.simhash.num_bands` | int | 4 | - | - | - | **배제** | Number of Bands | 위와 동일 |
| `dedup.simhash.simhash_bits` | int | 64 | - | - | - | **배제** | SimHash Bits | 위와 동일 — `hamming_*_threshold` 상한의 근거값이기도 함 |

### 2.2 ingestion 하위 확장 필드 — rag-ent-api 전용 (`rag_ent/config/settings.py`)

이 저장소(rag-api) 소스에는 없는 필드다 — `IngestionSettings`를 상속하는 배포(rag-ent-api)에서만
존재하며, `resolve_settings()`가 `type(base)`로 실제 서브클래스를 재구성하기 때문에 override
경로에는 그대로 올라온다. `ingestion.` 접두사이므로 allow-list는 통과한다. 배제 여부는 지금
rag-ent-api 자체 `ENT_EXCLUDED_OVERRIDE_KEYS`(rag-api `EXCLUDED_OVERRIDE_KEYS`와 동일한 성격의
분리된 frozenset)가 별도로 관리하는데, §4가 rag-api 쪽 deny-list를 필드 메타데이터로 없애는
것과 같은 이유로 이것도 없어져야 한다 — `image_captioning.model` 필드 선언에
`json_schema_extra={"override": False}`를 붙이고 `ENT_EXCLUDED_OVERRIDE_KEYS` frozenset과
그걸 감싸는 `rag_ent.config.settings.validate_override_key` 래퍼 함수를 제거한다.

| dot-key | 타입 | 기본값 | enum | min | max | override | description(제안) | 비고 |
|---|---|---|---|---|---|---|---|---|
| `ingestion.image_captioning.enabled` | bool | `false` | - | - | - | 가능 | Enabled | |
| `ingestion.image_captioning.model` | str | `qwen2.5vl:3b` | - | - | - | **배제** | Model | 모델 pull/GPU 메모리 등 운영 결정, KB 단위로 바꾸면 조용히 실패 위험 — 배제 메커니즘은 위 문단대로 필드 메타데이터로 이관 |
| `ingestion.image_captioning.temperature` | float | 0.1 | - | 0.0 | 2.0 | 가능 | Temperature | VLM temperature 통상 범위로 추정 |
| `ingestion.image_captioning.max_images_per_doc` | int | 20 | - | 1 | 200 | 가능 | Max Images / Doc | 상한은 대용량 문서 지연 가드레일 |
| `ingestion.image_captioning.max_concurrent_tasks` | int | 5 | - | 1 | 20 | 가능 | Max Concurrent Tasks | `asyncio.Semaphore` 크기 — `queue_worker.max_workers`(기본 4, 비override) 대비 여유 상한 |
| `ingestion.image_captioning.default_language` | str | `ko` | (ISO 639-1) | - | - | 가능 | Default Language | 자유 문자열 — enum으로 못박기보다 ISO 639-1 2자리 패턴 검증이 더 적합할 수 있음 |
| `ingestion.pdf_ocr_fallback.enabled` | bool | `false` | - | - | - | 가능 | Enabled | |
| `ingestion.pdf_ocr_fallback.engine` | str | `rapidocr` | (현재 값 1개뿐) | - | - | 가능 | OCR Engine | 사실상 상수 — 엔진이 하나뿐이라 `Literal["rapidocr"]` 승격은 실익 낮음 |
| `ingestion.pdf_ocr_fallback.language` | str | `korean` | (RapidOCR `Rec.lang_type` 값) | - | - | 가능 | OCR Language | RapidOCR이 지원하는 값 목록으로 enum화 가능하나 이번 설계에서 목록을 확정하지 않음 |
| `ingestion.pdf_ocr_fallback.min_chars_per_page` | int | 50 | - | 0 | 2000 | 가능 | Min Chars / Page | |
| `ingestion.table_layout.enabled` | bool | `false` | - | - | - | 가능 | Enabled | |
| `ingestion.table_layout.scan_region_min_score` | float | 0.5 | - | 0.0 | 1.0 | 가능 | Scan Region Min Score | RapidLayout 신뢰도 점수 |
| `ingestion.table_layout.scan_region_fragment_merge_gap_pt` | int | 20 | - | 0 | 200 | 가능 | Fragment Merge Gap (pt) | 필드 주석의 실측값(구매내역서.pdf ~52pt)보다 넉넉한 상한 |

### 2.3 override 구조적 배제 그룹 (allow-list 밖)

base 문서 §9.1의 접두사 allow-list(`ingestion.`/`chunking.`/`dedup.`)가 먼저 걸러내므로, 아래
그룹은 필드 단위 min/max 논의 자체가 불필요하다 — deny-list에 없어도 애초에 통과할 수 없다.
rag-api 자체 `Settings`의 15개 top-level 그룹(§2.1의 `ingestion`/`chunking`/`dedup`을 제외한
전부)과, rag-ent-api `Settings`가 상속에 추가로 얹는 4개 그룹(`oidc`/`authz`/`smtp`/
`rate_limit` — §2.2의 `ingestion` 하위 확장과 달리 이쪽은 아예 새로운 top-level 섹션)을 모두
포함한다.

| 그룹 | 대표 필드 | 배제 사유 |
|---|---|---|
| `server` | `production`, `workers` | 프로세스 배포 단위 설정 |
| `dagster` | `endpoint` | 인프라 접속 정보 |
| `s3` | `access_key`, `secret_key`, `endpoint` | 인프라 자격증명 — base 문서 §9.1이 명시적으로 경계한 케이스 |
| `redis` | `host`, `password` | 인프라 자격증명/접속 정보 |
| `postgres` | `host`, `user`, `password` | 인프라 자격증명/접속 정보 |
| `qdrant` | `host`, `port` | 인프라 접속 정보 |
| `queue_worker` | `max_workers` | 프로세스 전역 `ThreadPoolExecutor` 크기 — 재사용 객체(base 문서 §7) |
| `queue_poll` | `poll_interval_sec` | 프로세스 전역 폴링 루프 설정 |
| `provider` | `openai_api_key`, `ollama_url` | 인프라 자격증명/접속 정보 |
| `embedding` | `model`, `vector_size` | Qdrant 컬렉션의 벡터 차원과 고정 결합 — KB별로 바꾸면 기존 인덱스와 차원 불일치 |
| `retrieval` | `mode`, `top_k`, `hybrid.*`, `rerank.*` | 검색 시점 설정 — 이번 오버라이드 범위는 인제스트 파이프라인(ingestion/chunking/dedup)뿐, 검색 파라미터는 범위 밖 |
| `mcp` | `transport`, `port` | 프로세스 기동 설정 |
| `tracing` | `langfuse_secret_key` | 인프라 자격증명 |
| `logging` | `level`, `names` | 프로세스 전역 로거 설정 |
| `knowledge_bases` | `id`, `tags` | KB 자체를 정의하는 목록 — 오버라이드 대상이 아니라 오버라이드의 키(`kb_id`) |
| `oidc` (rag-ent-api) | `admin_client_id`, `admin_client_secret` | 인프라 자격증명(OIDC 관리자 클라이언트) |
| `authz` (rag-ent-api) | `super_admin_role`, `invite_expiry_days` | 인가 정책 — 프로세스 전역, KB 단위 개념 아님 |
| `smtp` (rag-ent-api) | `host`, `username`, `password` | 인프라 자격증명/접속 정보 |
| `rate_limit` (rag-ent-api) | `rules`, `default`, `exempt_paths` | 프로세스 전역 요청 제한 정책 — KB가 아니라 API 엔드포인트 단위 |

## 3. cross-field 제약 — 단일 필드 range로 안 잡히는 것

§2.1 표에서 식별된 cross-field 제약을 모두 모으면 다음과 같다. `Field(ge=, le=)`만으로는 못 잡고
`ChunkingSettings`/`DedupSettings`류에 `model_validator(mode="after")` 같은 모델 단위 검증이
필요하다 — base 문서 §9.1 검증 순서의 4번(`type(base)(**merged)` 재검증) 자리에 태운다.

| 제약 |
|---|
| `chunking.chunk_overlap < chunking.chunk_size` |
| `chunking.code_chunk_lines_overlap < chunking.code_chunk_lines` |
| `dedup.chunk_compare.body_similar_threshold <= dedup.chunk_compare.body_identical_threshold` |
| `dedup.simhash.hamming_identical_threshold <= dedup.simhash.hamming_similar_threshold` |
| `dedup.simhash.hamming_*_threshold`가 오버라이드 불가 필드인 `dedup.simhash.simhash_bits`(그 KB의 현재 전역값)를 상한으로 참조 |
| `dedup.minhash.title_only_min_jaccard_floor`와 `dedup.minhash.jaccard_threshold`의 관계 — floor가 threshold보다 항상 낮아야 하는 제약인지 독립 임계값인지는 `dedup/minhash.py` 확인 후 결정, 이번 설계에서 확정하지 않음 |

**저장 시점 검증 실패의 에러 응답 형태는 이 문서 범위 밖이다.** rag-admin
`kb-settings-override-ui.md` §7은 "400 응답 → 필드 하나에 인라인 에러"를 가정하지만,
`chunk_overlap < chunk_size`처럼 두 필드에 걸친 제약이 위반되면 어느 쪽 dot-key에 에러를 붙일지
이 가정만으로는 정해지지 않는다(실패 필드를 배열로 내려줄지, 대표 필드 하나로 응답할지 등). 이
결정은 구현 착수 시 rag-admin과 맞춘다 — 필드 스키마 자체를 정의하는 이 설계의 범위에는 포함하지
않는다.

## 4. override 메타데이터 — `json_schema_extra`

`EXCLUDED_OVERRIDE_KEYS`(frozenset, 필드 선언과 분리된 문자열 목록, base 문서 §5)를 필드 선언
옆 Pydantic 메타데이터로 옮긴다:

```python
class MinHashSettings(BaseModel):
    jaccard_threshold: float = 0.65
    title_fuzzy_threshold: float = 0.85
    title_only_min_jaccard_floor: float = 0.25
    # process-global Kiwi tokenizer singleton — see kb-settings-override.md §5
    user_words_path: str = Field(default="", json_schema_extra={"override": False})
```

`json_schema_extra`는 `{"override": False}` 한 키만 싣는다 — 배제 사유는 base 문서 §5 표에
이미 있으므로 필드 옆에는 코드 주석으로만 남기고 `json_schema_extra` 딕셔너리에는 넣지 않는다.
키는 `overridable`이 아니라 `override`로 쓰고, **override를 막아야 하는 필드에만** 붙인다 —
나머지 대다수 필드(§2.1/§2.2에서 "가능"으로 분류된 필드)는 아무 메타데이터도 선언하지 않는다.

**`EXCLUDED_OVERRIDE_KEYS`(deny-list)는 없어지고 이 메타데이터로 완전히 대체된다.
`OVERRIDABLE_SETTINGS_PREFIXES`(allow-list, `("ingestion.", "chunking.", "dedup.")`)는
그대로 남는다** — 이 둘은 계층이 다르다. allow-list는 "이 top-level 섹션 자체가 override
후보군인가"를 가르는 것이고, 필드 메타데이터는 "그 후보군 안에서 이 필드 하나는 예외로
막을 것인가"를 가르는 것이다. allow-list를 없애고 필드 메타데이터(기본값 `override: True`)만
남기면, `provider.openai_api_key`/`redis.password`/`s3.secret_key`처럼 지금은 애초에
후보군에도 못 들어오는 인프라 자격증명 필드까지 "메타데이터가 없으니 기본 허용"으로 뚫려버린다
— base 문서 §9.1이 "deny-list만으로는 안전하지 않다"며 allow-list를 deny-list보다 먼저
적용하기로 한 이유(§10 대안 비교)가 그대로 재발하는 것이므로, allow-list는 반드시 유지한다.

`validate_override_key`(base 문서 §9.1)는 이렇게 바뀐다 — allow-list 체크(1번)는 그대로 두고,
기존에 별도 단계였던 deny-list 체크(2번, `EXCLUDED_OVERRIDE_KEYS` 조회)를 없애는 대신, 필드
경로 존재 확인을 위해 어차피 하던 `model_fields` 순회(3번, 국문 초안 기준)의 마지막 리프
필드에서 `override` 플래그까지 함께 확인한다 — 두 단계였던 걸 한 번의 순회로 합친다:

```python
def validate_override_key(settings_cls: type[BaseModel], dotted_key: str) -> None:
    if not dotted_key.startswith(OVERRIDABLE_SETTINGS_PREFIXES):  # allow-list, 그대로 유지
        raise IngestValidationError(f"Settings key not overridable: {dotted_key!r}")

    node: Any = settings_cls
    field = None
    for part in dotted_key.split("."):
        if not (isinstance(node, type) and issubclass(node, BaseModel)):
            raise IngestValidationError(f"Unknown settings key: {dotted_key!r}")
        field = node.model_fields.get(part)
        if field is None:
            raise IngestValidationError(f"Unknown settings key: {dotted_key!r}")
        node = field.annotation

    # EXCLUDED_OVERRIDE_KEYS frozenset 조회를 대체 — 같은 순회의 리프 필드에서 바로 확인
    if not (field.json_schema_extra or {}).get("override", True):
        raise IngestValidationError(f"Settings key not overridable: {dotted_key!r}")
```

- 지금 구조는 새 필드를 `ingestion`/`chunking`/`dedup` 아래 추가할 때 배제 처리를 깜빡하면
  조용히 오버라이드 가능해진다 — base 문서 §9.1이 우려하는 "잘못된 값이 조용히 저장"과 같은
  종류의 드리프트 위험. 메타데이터를 필드 선언 옆에 두면 이 위험이 줄어든다.
- **기각한 대안**: 값 자체를 `{float: 0.65, override: true, ...}` 같은 dict/object로 감싸는
  안. `Settings`는 지금 코드베이스 전체(파이프라인 step, dagster op, dedup 비교 로직,
  rag-ent-api 확장 등)에서 `cfg.dedup.minhash.jaccard_threshold`를 plain 값으로 그대로
  쓴다 — 값을 감싸면 이 모든 호출부를 언랩하도록 고쳐야 하는 큰 리팩터가 되고, 런타임 config
  (hot path)와 UI 스키마 메타데이터(관리자 화면만 씀)를 한 타입에 섞게 된다.
  `json_schema_extra`는 필드 값 타입을 바꾸지 않으므로 기존 호출부 전부 무영향.
- `validate_override_key`(base 문서 §9.1)와 §5의 `/settings/schema` 엔드포인트가 이
  메타데이터를 같은 소스로 읽는다 — 검증 로직과 스키마 응답이 갈라지지 않는다.
- §2.1의 `min`/`max`도 같은 방식으로 `Field(ge=, le=)`에 실어 선언 시점에 함께 둔다 —
  `override` 메타데이터와 마찬가지로 필드 선언과 분리된 별도 상수 테이블을 새로 만들지 않는다.

### 4.1 enum이 필요한 필드 — `json_schema_extra`가 아니라 `Literal`

`override`/`min`/`max`와 달리 enum은 별도 메타데이터 키가 필요 없다 — Pydantic 타입 자체를
`Literal[...]`로 선언하면 §5의 `/settings/schema`가 `typing.get_args(field.annotation)`로
그대로 뽑아 쓸 수 있다. `ingestion.html_extraction_policy`가 이미 이 패턴이다:

```python
html_extraction_policy: Literal["strict", "lenient", "balanced"] = "lenient"
```

**`chunking.strategy`는 아직 이 패턴을 안 따른다** — `str = "recursive"`로 선언되어 있어 어떤
문자열이든 Pydantic 검증을 통과한다. 그런데 유효한 값 집합은 이미 다른 곳에 타입으로 존재한다 —
`pipeline/steps/chunk.py`의 `ChunkStrategy = Literal["recursive", "semantic"]`. `ChunkingSettings`가
이 타입을 재사용하지 않고 별도로 `str`을 선언해 두 군데가 따로 논다:

```python
# config/settings.py — 변경 전
class ChunkingSettings(BaseModel):
    strategy: str = "recursive"

# config/settings.py — 변경 후 (pipeline/steps/chunk.py의 ChunkStrategy 재사용)
from rag_api.pipeline.steps.chunk import ChunkStrategy

class ChunkingSettings(BaseModel):
    strategy: ChunkStrategy = "recursive"
```

이건 스키마 엔드포인트 설계를 넘어서는 **기존 검증 공백**이다 — 지금도(오버라이드 여부와 무관하게)
`settings.yaml`에 `chunking.strategy: "typo"`를 넣으면 `Settings.from_yaml()`이 조용히 통과시키고,
실제로 문서를 청킹하는 시점에야 `chunk.py:_build_parser`의 `raise ConfigError(f"Unknown chunking
strategy: {strategy}")`로 뒤늦게 실패한다. `Literal`로 승격하면 이 실패가 설정 로드/오버라이드
저장 시점으로 앞당겨진다 — base 문서 §9.1이 이미 KB override 저장 시점에 `type(base)(**merged)`
재검증을 하므로, `Literal`만 승격하면 별도 코드 변경 없이 그 재검증이 `strategy`도 잡아준다.

`document_aware`는 넣지 않는다 — `settings.py`의 기존 인라인 주석(`# recursive / semantic /
document_aware (pending US-03)`)은 US-03 계획을 반영한 것이지 지금 구현된 값이 아니다. `Literal`을
실제 구현(`chunk.py`)이 아니라 계획 주석 기준으로 넓게 잡으면, 유효하지 않은 `document_aware`가
검증을 통과해 §2.1이 원래 막으려던 것과 같은 종류의 "타입은 맞지만 의미상 실패"가 재발한다 — US-03이
실제로 구현되어 `chunk.py`의 `ChunkStrategy`에 값이 추가될 때 이쪽도 자동으로 따라간다(같은 타입을
재사용하므로).

### 4.2 필드 label — `json_schema_extra`가 아니라 Pydantic 네이티브 `description`

rag-admin `kb-settings-override-ui.md` §4의 와이어프레임은 `max_file_size_mb` →
"Max File Size **(MB)**", `html_extraction_policy` → "**HTML** Extraction Policy"처럼 다듬어진
라벨을 쓴다. dot-key를 그대로 Title Case로 변환하면("Max File Size Mb", "Html Extraction
Policy") 약어 대문자화도 안 맞고 단위도 안 생긴다 — rag-admin이 필드 목록을 하드코딩하지 않겠다는
원칙을 지키려면 라벨도 스키마에서 와야 한다.

`override`는 Pydantic에 대응 개념이 없어서 `json_schema_extra`에 얹었지만(§4), description은
Pydantic `Field()`가 이미 1급으로 지원하는 파라미터다 — 새 메커니즘을 또 만들 필요가 없다:

```python
class IngestionSettings(BaseModel):
    max_file_size_mb: int = Field(default=200, description="Max File Size (MB)")
    min_content_chars: int = Field(default=200, description="Min Content Chars")
    html_extraction_policy: Literal["strict", "lenient", "balanced"] = Field(
        default="lenient", description="HTML Extraction Policy",
    )
```

`/settings/schema`가 `field.description`을 그대로 `description` 키로 응답에 실으면 rag-admin은
이 값을 라벨로 그대로 쓴다 — 별도 label/unit 필드를 새로 만들지 않고 문자열 하나로 끝낸다(현재
와이어프레임 라벨엔 툴팁용 긴 설명이 따로 없으므로, 짧은 표시용 문자열과 긴 설명을 분리할 이유가
아직 없다). §2.1/§2.2의 override 대상 필드 전부(rag-api + rag-ent-api)에 이 작업이 필요하다 —
지금은 일부 필드에 Python 주석으로만 설명이 달려 있고(예: `html_extraction_policy`의
strict/lenient/balanced 설명) 이런 주석은 런타임에 전혀 읽히지 않는다.

## 5. `GET /kb/{kb_id}/settings/schema` 엔드포인트

§4·§4.1·§4.2에서 `Settings`의 override 허용 여부/enum/min·max/description을 전부 필드 선언
옆으로 옮기고 나면, 이 엔드포인트는 그 값들을 `Settings.model_fields` 순회로 그대로 직렬화하는
것뿐이다 — 별도로 설계할 로직이 거의 없다. rag-admin `kb-settings-override-ui.md` §8.2가 이
엔드포인트의 필요성을 먼저 지적했지만(ingestion/chunking/dedup 필드 목록을 하드코딩하지 않고
동적으로 폼을 그리려면 dot-key별 스키마가 필요하다), 그건 이 엔드포인트가 존재해야 하는 이유 중
하나일 뿐 설계의 출발점은 아니다 — §1에서 정리했듯 `Settings` 필드 자체의 결함(값 검증/
description/override 허용 여부)을 고치는 게 먼저고, 이 엔드포인트는 그 결과물을 외부에 노출하는
창구다. 응답에 dot-key별로 담기는 정보:

- `type`: `bool`/`int`/`float`/`str`/`enum` (Pydantic 어노테이션에서 파생 — `Literal[...]`이면
  `enum`, 아니면 스칼라 타입 그대로)
- `enum`: `type=enum`일 때 허용 값 목록(`Literal`의 `get_args`)
- `default`: 필드 기본값
- `overridable`: §4의 `json_schema_extra={"override": False}` 메타데이터에서 파생 —
  선언이 없으면 응답의 `overridable`은 기본 `true`, `override: False`가 명시된 필드만 `false`
  (내부 필드 메타데이터 키는 `override`, API 응답 필드명은 `overridable` — 후자는 rag-admin
  폼이 읽는 boolean 이름으로 자연스러운 형용사형을 그대로 유지)
- `min`/`max`: §2.1/§2.2의 range 제약을 `Field(ge=, le=)`에서 파생
- `description`: §4.2의 `Field(description=...)`에서 파생 — rag-admin이 라벨로 그대로 사용
- 소속 그룹: top-level 섹션(`ingestion`/`chunking`/`dedup`) + 서브섹션(예:
  `image_captioning`)

서버 쪽 신규 로직은 대부분 `Settings.model_fields`를 순회하며 위 정보를 직렬화하는 것뿐 —
`validate_override_key`가 쓰는 것과 같은 소스(§4)를 재사용한다. §2.3의 구조적 배제 그룹은
allow-list 접두사 자체로 걸러지므로 이 엔드포인트는 애초에 `ingestion`/`chunking`/`dedup`
서브트리만 순회하면 된다 — base 문서 §9.2의 `GET /kb/{kb_id}/settings`와 응답 범위가 같은 이유다.

**예외 — `dedup.simhash.hamming_identical_threshold`/`hamming_similar_threshold`만 정적
순회로 안 끝난다.** 이 둘의 진짜 상한은 코드에 박아둔 상수가 아니라 그 배포의
`dedup.simhash.simhash_bits`(오버라이드 불가, `settings.yaml`에서 오는 전역값) 자체다 — 예를
들어 `simhash_bits: 64`인 배포라면 `[0, 64]`가 맞지만, 어떤 배포가 `simhash_bits: 32`로 띄웠다면
진짜 상한은 32다(두 32비트 해시 사이의 hamming distance는 32를 넘을 수 없다). 이 두 필드를 Python
소스에 `Field(le=64)`처럼 정적으로 박아두면 `simhash_bits: 32`인 배포에서 스키마 응답이 여전히
`max: 64`라고 거짓말하게 되고, rag-admin은 그 배포에서 의미 없는 `50` 같은 값을 그대로 통과시킨다.
그래서 이 두 필드만은 `Field()` 메타데이터를 읽는 대신 응답 직렬화 시점에
`get_settings().dedup.simhash.simhash_bits`를 조회해 `max`를 그때그때 계산해 넣는 특별 처리가
필요하다 — "그냥 `model_fields` 순회"로 끝나지 않는 유일한 필드.
