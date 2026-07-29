# KB별 설정 오버라이드

순수 기술 설계 문서 — 특정 PRD 섹션에 대응되지 않는다(요건 없음). `settings.yaml`의 `ingestion:`
/ `chunking:` / `dedup:` 값을 KB 단위로 오버라이드할 수 있게 하는 기반 아키텍처를 정의한다.
rag-api를 대상으로 하며(리졸버, 저장 스키마, REST API, 파서 레지스트리 재설계), 각 필드를
실제로 소비하는 rag-ent-api 쪽 변경(플러그인 `register()` 시그니처 등)은 [`parser-registry.md`](parser-registry.md)와
연결되는 후속 작업으로 §8에서 범위만 짚는다.

## 1. 배경

`settings.yaml`은 프로세스 전체에 적용되는 단일 설정이다. 그런데 `ingestion`/`chunking`/`dedup`
아래 값들은 실제로는 KB마다 다르게 필요할 수 있다(예: 어떤 KB는 이미지 캡셔닝이 필요 없고,
어떤 KB는 청크 크기를 다르게 써야 함). 지금은 이걸 하려면 KB별로 별도 배포(프로세스)를 띄우는
수밖에 없다.

목표는 `connectors.config JSONB` + `config.get(key, get_settings()...)` 패턴(`connectors/web.py`)을
전역 설정 전체로 일반화하는 것 — KB가 오버라이드를 저장해두면, 파이프라인이 그 값을 우선
쓰고 없으면 전역 `settings.yaml` 값으로 폴백한다.

```
파이프라인 스텝 → kb_config(override) 조회 → 없으면 전역 settings.yaml 값
```

## 2. 핵심 원칙

**등록(register)과 활성화(enabled)를 분리한다.** 파서/후처리기 "등록"(어떤 확장자가 존재하는가)은
프로세스 시작 시 설정과 무관하게 무조건 1회 수행하고, "활성화 여부/파라미터"는 매 호출 시점에
KB 스코프로 판단한다. 이 원칙 하나로 두 가지 문제가 동시에 풀린다:

- KB별로 기능을 껐다 켰다 할 때 "전역이 꺼져있으면 KB가 켤 수 없는" 비대칭이 없어진다(등록 자체가
  설정에 의존하지 않으므로).
- 프로세스 재사용 환경(QueueWorker, §7)에서 "최초 1회 등록 시점의 설정이 그 프로세스 수명 내내
  고정되는" 문제가 없어진다(등록에 설정이 관여하지 않으므로 재사용해도 안전).

## 3. 리졸버

`config/settings.py`에 KB 스코프 리졸버를 하나 추가한다. [`settings-composition.md`](settings-composition.md)의
`get_settings()`/`set_settings()` 계약 위에 얹히며, rag-ent-api가 `Settings`를 상속해 필드를
추가해도(`image_captioning` 등) 이 함수는 그 존재를 몰라도 되게 제네릭하게 동작한다.

```python
def resolve_settings(kb_id: str | None) -> Settings:
    """전역 Settings에 KB override(플랫 dot-key dict)를 병합해 반환한다. kb_id가 None이거나
    override가 없으면 전역 인스턴스를 그대로 반환한다 — 새 객체를 만들지 않는다."""
    base = get_settings()
    if kb_id is None:
        return base
    overrides = get_kb_settings_overrides(kb_id)  # infra/postgres.py, 없으면 {} — {"ingestion.max_file_size_mb": 50, ...}
    if not overrides:
        return base
    merged = _apply_dotted_overrides(base.model_dump(), overrides)
    return type(base)(**merged)  # 실행 중인 실제 서브클래스로 재검증


def _apply_dotted_overrides(base: dict, overrides: dict[str, Any]) -> dict:
    """{"ingestion.image_captioning.enabled": false} 같은 dot-key를 base(중첩 dict)에 적용."""
    for dotted_key, value in overrides.items():
        *path, leaf = dotted_key.split(".")
        node = base
        for part in path:
            node = node.setdefault(part, {})
        node[leaf] = value
    return base
```

- `type(base)`로 재구성하는 이유: rag-ent-api가 상속한 서브클래스 그대로 반환되게 하기 위함(§2 원칙과
  동일하게 rag-api 코드는 자기 필드만 알면 됨).
- override가 없는 KB(대다수)는 `base`를 그대로 반환해 매 호출마다 불필요한 객체 생성이 없다.
- 호출부는 기존 `get_settings().ingestion.x` 자리를 `resolve_settings(kb_id).ingestion.x`로
  기계적으로 바꾸기만 하면 된다 — 이 문서 §6의 나머지 절이 그 목록이다.

**주의 — 잘못된 키는 여기서 걸러지지 않는다.** `Settings`에 `model_config`가 없어 Pydantic
기본값(`extra="ignore"`)을 그대로 쓴다. 즉 존재하지 않는 필드 경로가 `overrides`에 들어 있어도
`type(base)(**merged)`는 조용히 무시할 뿐 에러를 내지 않는다. 더 나쁜 경우도 있다 —
`dedup.enabled.foo`처럼 이미 스칼라인 경로를 한 단계 더 파고드는 키가 저장되면,
`_apply_dotted_overrides`의 `node.setdefault(part, {})`가 기존 스칼라 값(`True`/`False`)을
그대로 반환하고 다음 줄 `node[leaf] = value`가 `TypeError: 'bool' object does not support item
assignment`로 죽는다 — 이 KB는 이후 `resolve_settings()`를 호출할 때마다 예외가 나서 인제스트
자체가 막힌다. 그래서 이 검증은 리졸버(읽기 경로)가 아니라 **저장 시점(§9 PUT/PATCH)에서
명시적으로** 해야 한다 — 잘못된 키가 애초에 테이블에 들어가지 못하게 막는다.

## 4. 저장 스키마

`connectors.config JSONB` 선례를 그대로 따른다. 신규 마이그레이션 `migrations/002_kb_settings_overrides.sql`:

JSONB 블롭 하나에 flat dict를 통째로 넣는 대신, **행 하나 = 오버라이드 키 하나**인 진짜
key-value 테이블로 만든다 — 이 편이 PATCH(§9)를 SQL 레벨의 단순 upsert/delete로 바로 대응시킬
수 있다:

```sql
CREATE TABLE IF NOT EXISTS kb_settings_overrides (
    kb_id      TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    key        TEXT NOT NULL,       -- dot-notation, Settings 모델 필드 경로 그대로 (예: "ingestion.max_file_size_mb")
    value      JSONB NOT NULL,      -- 스칼라/객체 어떤 JSON 값이든 (bool/int/float/str/list)
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (kb_id, key)
);
```

`key`가 `.`으로 이어붙인 dot-notation인 이유는 이전과 동일(§3의 `_apply_dotted_overrides`가
그대로 소비) — 차이는 저장 단위가 "KB당 JSONB 블롭 1개"에서 "KB당 키 N개의 행"으로 바뀐 것뿐이다.
리졸버가 보는 논리적 모양은 여전히 같은 flat dict다:

```json
{
  "ingestion.max_file_size_mb": 50,
  "ingestion.image_captioning.enabled": false,
  "chunking.chunk_size": 512,
  "chunking.chunk_overlap": 64,
  "dedup.enabled": false
}
```

`infra/postgres.py`에 CRUD 추가(`00-hard-rules.md` #6 — 메타데이터 CRUD는 postgres.py 담당):

```python
def get_kb_settings_overrides(kb_id: str) -> dict[str, Any]:
    """SELECT key, value FROM kb_settings_overrides WHERE kb_id = %s — 행들을 dict로 조립."""

def upsert_kb_settings_override(kb_id: str, key: str, value: Any) -> None:
    """INSERT ... ON CONFLICT (kb_id, key) DO UPDATE SET value=..., updated_at=NOW() — 키 1개."""

def delete_kb_settings_override(kb_id: str, key: str) -> None:
    """DELETE FROM kb_settings_overrides WHERE kb_id=%s AND key=%s — 키 1개, 없어도 no-op."""

def replace_kb_settings_overrides(kb_id: str, overrides: dict[str, Any]) -> None:
    """트랜잭션 내 DELETE ALL + bulk INSERT — PUT(전체 교체)용."""

def clear_kb_settings_overrides(kb_id: str) -> None:
    """DELETE FROM kb_settings_overrides WHERE kb_id=%s — 이 KB의 오버라이드 전체 제거."""
```

## 5. 오버라이드 가능 필드 범위

`docker/settings.yaml`의 `ingestion:`/`dedup:`/`chunking:` 전체를 검토한 결과다.

| 그룹 | dot-key | 오버라이드 | 비고 |
|---|---|---|---|
| ingestion | `ingestion.max_file_size_mb`, `ingestion.min_content_chars`, `ingestion.html_extraction_policy` | 가능 | 매 문서 호출 시 읽음 |
| ingestion | `ingestion.pdf_ocr_fallback.*` | 가능 | 리더 내부에서 매 호출 판단(§6) |
| ingestion | `ingestion.table_layout.*` | 가능 | 리더 내부 판단(reader) + 후처리기 등록 무조건화 필요(§6) |
| ingestion | `ingestion.image_captioning.*` | 가능 | 등록 무조건화 + 리더 내부 판단으로 전환 필요(§6) |
| ingestion | `ingestion.parser_plugins` | **배제** | 배포 타임에 "어떤 모듈이 존재하는가"를 정하는 값 — KB별로 다르면 동일 확장자를 두 리더가 동시에 요구하는 상황이 생겨 last-writer-wins 구조와 충돌 |
| chunking | `chunking.strategy`, `chunking.chunk_size`, `chunking.chunk_overlap`, `chunking.min_chunk_chars`, `chunking.semantic_threshold`, `chunking.code_max_chars` | 가능 | 전부 순수 파라미터, 캐싱 없음 |
| dedup | `dedup.enabled`, `dedup.chunk_compare.*`, `dedup.minhash.jaccard_threshold`/`title_fuzzy_threshold`/`title_only_min_jaccard_floor`, `dedup.simhash.hamming_identical_threshold`/`hamming_similar_threshold` | 가능 | 매 비교 호출 시 파라미터로 전달 |
| dedup | `dedup.simhash.ngram`/`num_bands`/`simhash_bits` | **배제** | 이미 Postgres `simhash_bands`에 저장된 기존 문서의 지문과 계산 방식이 달라져 비교 불가능해짐(재인덱싱 없이는 위험) |
| dedup | `dedup.minhash.user_words_path` | **배제** | Kiwi 토크나이저가 프로세스 전역 싱글턴(`dedup/tokenizer.py`)으로 1회 로드 — KB별 경로를 지원하려면 경로 키 캐시가 별도로 필요, 이번 범위 밖 |

**(US-45로 갱신)** 배제 목록은 더 이상 별도 리터럴 문자열 집합(`EXCLUDED_OVERRIDE_KEYS`)이
아니다 — 각 필드 선언 옆 `json_schema_extra={"override": False}`로 이관되었다. 상세 설계와
값 검증(`Field(ge=/le=)`)·description·`GET /kb/{kb_id}/settings/schema`는
[`kb-settings-override-schema.md`](kb-settings-override-schema.md)를 참고한다. 위 표의 "배제"
필드는 여전히 유효하며, 구현 위치만 바뀌었다:

```python
# config/settings.py — 필드 선언 옆
class MinHashSettings(BaseModel):
    ...
    user_words_path: str = Field(default="", json_schema_extra={"override": False})
```

오버라이드 저장 API(§9)는 요청 body의 키 중 `override: False`로 표시된 필드가 있으면 명시적으로
거부한다(무시하지 않음 — 사용자가 "됐다"고 착각하는 걸 방지).

## 6. 파서 레지스트리 재설계

### 6.1 현재 구조의 문제

`pipeline/steps/parser/registry.py`는 module-level 전역 dict(`_parsers`, `_post_processors`)와
`_loaded` 래치로 되어 있다:

```python
def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return          # 두 번째 호출부터는 재실행 안 됨
    _register_defaults()
    _load_plugins()      # get_settings().ingestion.parser_plugins 순회하며 각 register() 실행
    _loaded = True
```

`image_ocr.py`/`table_layout.py`의 `register()`는 지금 등록 시점에 `cfg.enabled`를 확인해서
조건부로 리더/후처리기를 등록한다. 문제는 이 등록이 **프로세스 수명 동안 딱 1번**만 실행된다는
것 — QueueWorker(§7)처럼 프로세스가 재사용되는 환경에서는 최초로 이 코드를 실행시킨 순간의
설정(그때 우연히 처리 중이던 문서의 KB 설정, 혹은 전역 기본값)이 이후 모든 KB/문서에 그대로
고정된다. `resolve_settings(kb_id)`로 바꿔치기해도 `register()` 자체가 다시 안 불리면 의미가 없다.

### 6.2 변경 방향

등록은 설정과 완전히 무관하게 만든다 — `pdf_ocr_fallback`/`table_layout`의 `.pdf` reader가 이미
이 패턴이다(`image_ocr.py:31-33`, `table_layout.py:29-32` — "항상 교체, 활성화 여부는 리더
내부에서 판단"). 이 패턴을 `image_captioning`과 `table_layout`의 후처리기 등록까지 확장한다.

```python
# image_ocr.py — 변경 후
def register() -> None:
    register_parser(".pdf", PyMuPDFOCRFallbackReader())
    register_post_processor(caption_embedded_images)      # 무조건 등록
    for ext in IMAGE_EXTENSIONS:
        register_parser(ext, VLMCaptionReader())            # 무조건 등록
    # cfg.enabled 조건문 삭제 — registry.py는 더 이상 설정을 안 읽음
```

```python
# table_layout.py — 변경 후
def register() -> None:
    register_parser(".pdf", TableAwarePyMuPDFReader())
    register_post_processor(extract_tables)                # 무조건 등록 (기존엔 조건부)
```

리더/후처리기 내부는 이미 stateless라 큰 변경이 없다 — `PyMuPDFOCRFallbackReader.load_data()`,
`VLMCaptionReader.load_data()` 모두 `__init__`에 설정을 안 받고 매 호출 시 설정을 새로 읽는
구조다(`pdf_ocr_reader.py:26,29`, `vlm_caption_reader.py:23,27`). 여기서 읽는 소스만
`get_settings()` → `resolve_settings(kb_id).ingestion...`로 교체한다.

`image_captioning`은 지금까지 "비활성화 시 미등록 확장자로 처리"(`parse()`가 `Unsupported file
format` 거부)에 의존했는데, 등록을 무조건화하면 이 폴백이 사라진다. 대신 `VLMCaptionReader.load_data()`
안에서 직접 동일한 예외를 던진다:

```python
def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
    kb_id = (extra_info or {}).get("kb_id")
    cfg = resolve_settings(kb_id).ingestion.image_captioning
    if not cfg.enabled:
        raise IngestValidationError(f"Unsupported file format: {Path(file).suffix}")
    ...
```

이러면 전역 기준 동작이 기존과 완전히 동치이면서, KB별로 켜고 끄는 게 대칭적으로(켜기/끄기
둘 다) 가능해진다.

**후처리기는 리더와 판단 결과가 다르다.** `caption_embedded_images`(PDF 내장 이미지 캡셔닝,
case A)는 리더처럼 "이 문서를 거부"할 수 없다 — 후처리기는 이미 파싱된 `documents`에 캡션을
*추가*하는 역할이라, 비활성화 시에는 예외를 던지는 게 아니라 아무것도 추가하지 않고 넘어가야
한다(PDF 자체는 캡션 없이도 정상적으로 색인되어야 함):

```python
def caption_embedded_images(
    documents: list[Document], file_path: Path, suffix: str, kb_id: str | None,
) -> list[Document]:
    cfg = resolve_settings(kb_id).ingestion.image_captioning
    if not cfg.enabled or suffix != ".pdf":
        return []          # 리더와 달리 raise가 아니라 no-op — 문서 자체는 그대로 색인됨
    ...
```

`table_layout`의 `extract_tables` 후처리기도 동일한 형태(`cfg.enabled`가 꺼져 있으면 `[]`)로
바꾼다.

### 6.3 kb_id를 리더/후처리기까지 전달하는 배관

**리더**: `load_data(file, extra_info)`는 LlamaIndex `BaseReader` 인터페이스다. `SimpleDirectoryReader`의
`file_metadata` 콜백으로 `extra_info`에 kb_id를 실어 보낸다.

**후처리기는 리더와 다른 경로가 필요하다.** `registry.py`의 `PostProcessor` 타입과 `parse.py`의
호출부는 지금 kb_id/extra_info를 아예 받지 않는다:

```python
# registry.py — 현재
PostProcessor = Callable[[list[Document], Path, str], list[Document]]

# parse.py — 현재
for post_process in parser.get_post_processors():
    documents.extend(post_process(documents, file_path, suffix))
```

`extra_info`가 리더 안에서 `doc.metadata`로 병합되는 건 리더 구현마다 제각각이라(일부 커스텀
리더만 명시적으로 `metadata.update(extra_info)`를 함) 후처리기가 `documents[0].metadata`를 통해
kb_id를 얻는 방식에 의존하지 않는다 — `PostProcessor` 타입 자체를 확장해 명시적으로 전달한다:

```python
# registry.py — 변경 후
PostProcessor = Callable[[list[Document], Path, str, str | None], list[Document]]  # + kb_id

# parse.py — 변경 후
for post_process in parser.get_post_processors():
    documents.extend(post_process(documents, file_path, suffix, kb_id))
```

이건 `parser-registry.md` §2.3/§3에 문서화된 `register_post_processor(fn: Callable[[list[Document],
Path, str], list[Document]])` 계약을 바꾸는 것이라, 그 문서도 같이 갱신해야 한다(§10에 후속
작업으로 기록).

```python
# parse.py
def parse(doc_id: str, kb_id: str, storage_key: str, local_path: Path | None = None) -> list[Document]:
    ...
    reader = SimpleDirectoryReader(
        input_files=[str(file_path)],
        file_extractor=parsers if parsers else None,
        file_metadata=lambda _: {"kb_id": kb_id},
    )
```

`parse()` 시그니처에 `kb_id` 파라미터 추가가 필요하다(현재는 `doc_id`/`storage_key`만 받음 —
`pipeline/steps/CLAUDE.md`에 문서화된 계약과 실제 코드가 어긋나 있던 부분).

### 6.4 `_loaded` 래치는 그대로 둔다

등록이 설정과 무관해졌으므로 `_ensure_loaded()`의 "프로세스당 1회" 래치 자체는 문제가 안 된다 —
어떤 확장자가 등록되어 있는지는 이제 모든 KB에 공통이고, 그 확장자를 실제로 어떻게 처리할지만
KB별로 갈리기 때문이다. `ParserRegistry`를 인스턴스화해서 매번 새로 만드는 방식은 검토했으나
불필요 — §7에서 이유를 다룬다.

## 7. 왜 이 설계가 필요한가 (실행 모델 검증)

두 실행 경로의 프로세스 재사용 여부를 직접 확인했다.

**Dagster**: `docker/dagster.yaml`에 `run_launcher:`가 없어 기본값 `DefaultRunLauncher` 사용 —
run 하나당 `dagster api execute_run` 서브프로세스를 새로 띄운다. `run_coordinator:
QueuedRunCoordinator`(`max_concurrent_runs: 8`)로 동시에 여러 run이 돌 수 있지만 각자 독립
프로세스라 모듈 전역 상태를 공유하지 않는다. 이 경로만 있었다면 원래 코드로도 문제가 없었을
것이다(run == 프로세스 수명이 이미 일치).

**QueueWorker**(`pipeline/queue/queue_worker.py`, non-Dagster 모드): FastAPI 프로세스 안에서
`asyncio` 백그라운드 태스크로 도는 **단일 장기 실행 객체**다.

```python
class QueueWorker:
    def __init__(self, max_workers: int = 4, ...) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, ...)  # 프로세스 수명 내내 재사용

    async def _run_ingest(self, event: dict) -> None:
        async with self._semaphore:
            chunk_count = await loop.run_in_executor(
                self._executor,
                lambda: run_ingest_pipeline(doc_id=doc_id, force=force),
            )
```

`_poll()`이 여러 `doc_id`를 연속으로 `asyncio.create_task(self._run_ingest(event))`로 넘기면,
서로 다른 KB의 문서가 **같은 프로세스의 여러 스레드에서 동시에** 처리된다. 이 경로가 있는 한
"등록 시점에 설정을 굳히는" 구조는 확실히 깨진다 — §6의 재설계가 선택이 아니라 필수인 이유다.

반대로 §3 `resolve_settings(kb_id)`는 읽기 전용이고 매 호출 새 값을 반환할 뿐 공유 가변 상태를
쓰지 않으므로, 두 실행 경로 모두에서 안전하다.

## 8. rag-ent-api 쪽 변경 범위 (후속)

이 문서가 다루는 rag-api 쪽 변경(리졸버, 스키마, REST API, 레지스트리 등록 방식)이 선행되면,
rag-ent-api 쪽은 §6.2에 준하는 기계적 수정만 남는다:

- `image_ocr.py`/`table_layout.py`의 `register()`에서 `if cfg.enabled:` 가드 제거
- `PyMuPDFOCRFallbackReader`, `VLMCaptionReader`, `TableAwarePyMuPDFReader` 내부에서
  `get_settings()` → `resolve_settings(kb_id)`로 교체 (kb_id는 `extra_info`에서 획득, §6.3)
- `caption_embedded_images`, `extract_tables` 후처리기 시그니처에 `kb_id` 파라미터 추가하고
  내부에서 `resolve_settings(kb_id)` 사용 — 비활성화 시 `raise`가 아니라 `[]` 반환(§6.2)
- `rapidocr_engine.py`의 `_get_engine(language)` 값-키 캐시(§6.4와 동일 사상 — 이미 올바른
  패턴이므로 변경 불필요)

## 9. REST API

기존 `api/routers/kb.py` 패턴(`connectors.py`의 `config: dict[str, Any]` + 검증 함수 패턴)을
그대로 따른다 — `kb.py`에 서브 리소스 라우트를 추가한다.

```python
class KBSettingsOverrideRequest(BaseModel):
    overrides: dict[str, Any]   # {"ingestion.max_file_size_mb": 50, "chunking.chunk_size": 512, ...}
```

| 메서드 | 경로 | 동작 |
|---|---|---|
| `GET` | `/kb/{kb_id}/settings` | 유효 설정 조회 — `resolve_settings(kb_id)`의 `ingestion`/`chunking`/`dedup` **세 섹션만** 직렬화(§9.1) |
| `GET` | `/kb/{kb_id}/settings/schema` | **(US-45)** dot-key별 `type`/`enum`/`default`/`overridable`/`min`/`max`/`description`/그룹 — 필드 메타데이터 그대로 직렬화. 상세는 [`kb-settings-override-schema.md`](kb-settings-override-schema.md) §5 |
| `GET` | `/kb/{kb_id}/settings/overrides` | 이 KB에 저장된 override 원본 flat dict만 조회 (없으면 `{}`) |
| `PUT` | `/kb/{kb_id}/settings/overrides` | override flat dict **전체 교체** — body에 없는 기존 키는 사라짐(=전역으로 리셋) |
| `PATCH` | `/kb/{kb_id}/settings/overrides` | 기존 flat dict에 **키 단위 upsert** — body의 각 dot-key만 갱신/추가, 값이 `null`이면 그 키를 dict에서 제거(전역으로 리셋), body에 없는 기존 키는 그대로 유지 |
| `DELETE` | `/kb/{kb_id}/settings/overrides` | override 전체 삭제 (완전히 전역 값으로 리셋) |

`PATCH`는 key-value 테이블이라 body를 순회하며 키 하나마다 `value is None`이면
`delete_kb_settings_override(kb_id, key)`, 아니면 `upsert_kb_settings_override(kb_id, key, value)`를
그대로 호출하는 것으로 끝난다 — 기존 상태를 읽어와 병합한 뒤 다시 통째로 쓰는 read-modify-write가
필요 없다. `PUT`은 `replace_kb_settings_overrides(kb_id, overrides)`(트랜잭션 내 전체 삭제 후
bulk insert) 하나로 끝난다.

### 9.1 검증 — allow-list가 먼저다

**allow-list만으로는 안전하지 않다.** `Settings`에는 `ingestion`/`chunking`/`dedup` 말고도
`provider`(임베딩/LLM API 키), `redis`, `postgres`, `qdrant` 같은 인프라 자격증명 섹션이 있다.
deny 판정이 없으면 `overrides["provider.openai_api_key"]`나 `overrides["redis.host"]`처럼 §5가
다루지 않는 필드가 그대로 통과해 KB별로 인프라 자격증명/접속 정보를 덮어쓸 수 있게 된다. 그래서
**`ingestion.`/`chunking.`/`dedup.` 접두사로 시작하는 키만 애초에 허용하는 allow-list를 필드
단위 배제 판정보다 먼저** 적용한다.

**(US-45로 갱신)** 필드 단위 배제는 더 이상 별도 deny-list 조회 단계가 아니다 — §5에서 설명한
대로 `json_schema_extra={"override": False}`가 필드 선언 옆으로 옮겨지면서, 아래 3번(필드 경로
존재 확인)의 `model_fields` 순회 중 리프 필드에서 그 플래그까지 함께 확인하는 방식으로
합쳐졌다(2번이었던 별도 단계가 사라짐). 값 자체의 범위/타입 검증(구 4번)도 이제 인제스트
시점(`resolve_settings`)뿐 아니라 저장(PUT/PATCH) 시점에도 `validate_override_values`로
동일하게 수행된다 — 상세 설계는 [`kb-settings-override-schema.md`](kb-settings-override-schema.md)
§4를 참고.

`PUT`/`PATCH` 공통 검증 (순서대로):

1. **접두사 allow-list**: dot-key가 `ingestion.`/`chunking.`/`dedup.` 중 하나로 시작하지 않으면
   즉시 거부.
2. **필드 경로 존재 확인 + override 메타데이터 확인**(§3의 주의사항 — Pydantic 기본
   `extra="ignore"`에 기대면 안 됨): `type(base).model_fields`를 dot-key의 각 segment를 따라
   내려가며 존재 여부를 확인하고, 마지막 segment가 실제 leaf 필드가 아니면(예: 스칼라 필드를
   더 파고드는 경우) 거부한다. 그 리프 필드의 `json_schema_extra`에 `override: False`가 있으면
   거부한다 — 조용히 무시하지 않는다.
   ```python
   OVERRIDABLE_SETTINGS_PREFIXES = ("ingestion.", "chunking.", "dedup.")

   def validate_override_key(settings_cls: type[BaseModel], dotted_key: str) -> None:
       if not dotted_key.startswith(OVERRIDABLE_SETTINGS_PREFIXES):
           raise IngestValidationError(f"Settings key not overridable: {dotted_key!r}")
       node = settings_cls
       field = None
       for part in dotted_key.split("."):
           field = node.model_fields.get(part) if hasattr(node, "model_fields") else None
           if field is None:
               raise IngestValidationError(f"Unknown settings key: {dotted_key!r}")
           node = field.annotation
       if not (field.json_schema_extra or {}).get("override", True):
           raise IngestValidationError(f"Settings key not overridable: {dotted_key!r}")
   ```
3. 앞의 두 검증을 통과한 키만 `_apply_dotted_overrides` + `type(get_settings())(**merged)`
   재검증 경로를 태운다(`validate_override_values`) — 여기서는 타입/범위(`Field(ge=/le=)`,
   `Literal` 값 등)만 걸러진다. 이 경로는 저장 시점과 `resolve_settings()` 인제스트 시점 둘 다
   탄다.

값이 `null`인 경우는 "이 필드를 override 해제"로 해석한다(§9 표) — 이번 오버라이드 가능
필드셋(§5)에는 의미상 `None`을 허용하는 필드가 없으므로("비활성화"는 항상 `enabled: false`로
표현) 이 해석과 실제 값 사이의 충돌은 없다. `validate_override_values`는 `null` 키를 값 검증
대상에서 제외한다(호출부가 미리 걸러서 넘긴다).

### 9.2 `GET /kb/{kb_id}/settings` 응답 범위 제한

같은 이유로 `resolve_settings(kb_id)`를 통째로 직렬화해서 반환하면 안 된다 — 병합된 `provider`/
`redis`/`postgres`/`qdrant` 자격증명까지 API 응답에 노출된다. `ingestion`/`chunking`/`dedup`
세 섹션만 잘라 반환한다:

```python
@router.get("/kb/{kb_id}/settings")
async def get_kb_effective_settings(kb_id: str):
    cfg = resolve_settings(kb_id)
    return {
        "ingestion": cfg.ingestion.model_dump(),
        "chunking": cfg.chunking.model_dump(),
        "dedup": cfg.dedup.model_dump(),
    }
```

```python
# api/routers/kb.py — 나머지 추가분 스케치 (구현 없음, 시그니처만) — get_kb_effective_settings는 §9.2
@router.get("/kb/{kb_id}/settings/overrides")
async def get_kb_settings_overrides_endpoint(kb_id: str): ...

@router.put("/kb/{kb_id}/settings/overrides", status_code=200)
async def replace_kb_settings_overrides(kb_id: str, req: KBSettingsOverrideRequest): ...

@router.patch("/kb/{kb_id}/settings/overrides", status_code=200)
async def merge_kb_settings_overrides(kb_id: str, req: KBSettingsOverrideRequest): ...

@router.delete("/kb/{kb_id}/settings/overrides", status_code=200)
async def clear_kb_settings_overrides(kb_id: str): ...
```

## 10. 검토한 대안

| 대안 | 기각 이유 |
|---|---|
| `ParserRegistry`를 클래스로 바꿔 매 run/문서마다 새 인스턴스 생성 | 리더들이 이미 stateless(설정을 `load_data()`에서 매번 새로 읽음)라 불필요한 재구성 — §6.4 |
| 레지스트리를 run 시작 시점마다 재빌드(전역 dict를 그때그때 덮어씀) | QueueWorker의 스레드 동시성(§7)에서 서로 다른 KB의 run이 같은 전역 dict를 동시에 재작성하며 경합 — 근본적으로 불안전 |
| `parser_plugins`도 KB별 오버라이드 대상에 포함 | 동일 확장자에 대해 서로 다른 KB가 서로 다른 모듈을 기대하면 `register_parser`의 last-writer-wins 구조와 충돌(§5) |
| override 저장을 KB별로 완전히 자유로운 스키마(any dict)로 허용 | 배제 필드(§5)를 걸러낼 수 없어 재인덱싱 없이 dedup 정합성이 깨지는 값이 조용히 저장될 위험 |
| override를 `settings.yaml`과 같은 중첩 JSON object로 저장 | `PATCH`로 필드 하나만 갱신/해제하려면 중첩 경로를 순회하는 병합/삭제 로직이 필요해짐. flat dot-key dict는 키 하나 upsert/pop으로 끝나 구현·검증(§5 배제 목록 교집합 체크) 둘 다 단순해짐 |
| `connectors.config` 선례를 따라 KB당 JSONB 블롭 1개(`kb_id PK, overrides JSONB`)로 저장 | 커넥터는 PATCH도 항상 `config` 전체를 통째로 주고받아 블롭이 자연스럽지만, KB 오버라이드는 필드 단위 PATCH가 핵심 유즈케이스라 접근 패턴이 다름. 블롭 구조에서 PATCH는 필연적으로 read-modify-write가 되어, 서로 다른 키를 동시에 수정하는 두 PATCH 요청이 경합하면 낙관적 락 없이는 한쪽 변경이 조용히 유실됨(lost update). 행 단위 key-value 테이블(`PRIMARY KEY (kb_id, key)`)은 서로 다른 키에 대한 쓰기가 독립된 행 UPSERT라 이 경합이 구조적으로 없음 |
| override 저장 시점에 키 유효성 검증 없이 `resolve_settings`의 재검증(`type(base)(**merged)`)만 신뢰 | `Settings`가 `extra="forbid"`를 쓰지 않아(기본값 `"ignore"`) 존재하지 않는 필드는 조용히 무시되고, 스칼라 필드를 더 파고드는 잘못된 키는 `_apply_dotted_overrides`에서 `TypeError`로 크래시함 — 저장 시점(§9) 명시적 키 검증 필수 |
| 후처리기가 kb_id를 `documents[0].metadata`(리더가 채워둔 `extra_info`)에서 꺼내 쓰게 함 | `extra_info`→`metadata` 병합은 리더 구현마다 제각각(일부 커스텀 리더만 명시적으로 처리)이라 신뢰할 수 없음 — `PostProcessor` 타입 시그니처 자체에 kb_id를 추가해 명시적으로 전달(§6.3) |
| 오버라이드 키 검증을 `EXCLUDED_OVERRIDE_KEYS` deny-list만으로 처리 | `Settings`엔 `provider`(API 키)/`redis`/`postgres`/`qdrant` 등 §5가 다루지 않는 인프라 자격증명 섹션이 있어, deny-list에 없다는 이유로 그런 필드까지 KB별로 덮어쓸 수 있게 됨(보안 결함) — `ingestion.`/`chunking.`/`dedup.` 접두사 allow-list를 deny-list보다 먼저 적용(§9.1) |
| `GET /kb/{kb_id}/settings`가 `resolve_settings(kb_id)` 전체를 직렬화 | 병합된 `provider`/`redis`/`postgres` 자격증명이 API 응답에 그대로 노출됨 — `ingestion`/`chunking`/`dedup` 세 섹션만 잘라 반환(§9.2) |
