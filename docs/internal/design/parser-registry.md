# 파서 확장 레지스트리

> 요건: [prd.md §2](../requirement/prd.md#2-문서-인제스트) (파이프라인 단계 2. 파싱)

`pipeline/steps/parse.py`의 확장자 -> 리더 매핑을 정적 상수에서 **등록 기반 레지스트리**로 바꿔,
`parse.py`를 고치지 않고도 파서를 추가·교체·제거할 수 있게 한다.

## 1. 배경 (요약)

정적 딕셔너리는 파서 구현이 항상 이 저장소 안에 있고 지원 포맷이 배포마다 동일하다는 전제에서만
동작한다. 배포별로 다른 파서 구성이 필요해지거나 구현체가 저장소 밖에 있는 경우 이 전제가
깨진다 — 그래서 `parse.py` 수정 없이 확장 가능한 등록 구조가 필요하다.

등록을 애플리케이션 startup 훅(FastAPI 등)에 묶지 않고 `parse()`의 지연 로드로 처리하는 이유:
`parse()` 호출 진입점이 FastAPI/Dagster op/큐 워커/CLI로 여러 개라 단일 프레임워크 생명주기에
묶으면 다른 진입점에서 조용히 누락된다.

기본 파서도 특권 없이 동일한 등록 API를 쓰는 이유: 그래야 "기존 파서 교체/제거"에 별도 예외
처리가 필요 없다.

## 2. 구조

### 2.1 컴포넌트

| 컴포넌트 | 위치 | 역할 |
|---|---|---|
| 레지스트리 상태 | `pipeline/steps/parser/registry.py` | 확장자 -> 리더 매핑, 후처리 함수 목록을 모듈 전역으로 보관 |
| 등록 API | `register_parser()` / `unregister_parser()` / `register_post_processor()` | 레지스트리 상태를 변경하는 유일한 통로 |
| 조회 API | `supported_extensions()` | 현재 등록된 확장자 목록 반환 (기존 정적 상수 `SUPPORTED_EXTENSIONS` 대체) |
| 지연 로더 | `_ensure_loaded()` (내부) | 프로세스 내 최초 1회, 기본 파서 등록 -> 설정에 나열된 확장 로직 순차 실행 |
| 확장 로직 | 설정에 dotted path로 나열된 임의 모듈의 `register()` 함수 | 등록 API를 호출해 실제 추가/교체/제거 수행 (내용은 레지스트리가 알지 못함) |
| 기본 파서 로더 | `_register_defaults()` (내부) | rag-api 자체 리더(PDF/DOCX/MD/TXT/HWP/HTML 등)를 등록 API로 등록 — 특권 경로 없음 |

### 2.2 데이터 흐름

```
parse(doc_id, storage_key)
    │
    ▼
_ensure_loaded()  ── idempotent, 프로세스당 1회
    │
    ├─ 이미 로드됨 ──────────────────────────────► (skip)
    │
    └─ 최초 호출
         │
         ▼
    _register_defaults()            # 기본 리더 등록
         │
         ▼
    settings().ingestion.parser_plugins 순회
         │
         ▼
    각 항목 import → register() 호출  # 추가/교체/제거는 이 함수 내부의 register_parser/
         │                            # unregister_parser 호출로 결정됨
         ▼
    레지스트리 상태 확정
    │
    ▼
확장자로 리더 조회 → 파싱 실행
```

### 2.3 API (시그니처만 — 구현 없음)

```python
def register_parser(ext: str, reader: BaseReader) -> None: ...      # 있으면 교체, 없으면 추가
def unregister_parser(ext: str) -> None: ...                        # 제거
def register_post_processor(fn: Callable[[list[Document], Path, str], list[Document]]) -> None: ...
def supported_extensions() -> frozenset[str]: ...                   # _ensure_loaded() 포함
```

### 2.4 설정

```yaml
ingestion:
  parser_plugins: []   # "module.path:register_func_name" 문자열 목록
```

설정에는 "무엇을 로드할지"만 나열한다. 각 항목이 실제로 무엇을 등록/해제하는지는 그 모듈의
코드에 있다 — 설정은 스위치 역할만 한다.

**왜 배열인가**: 서로 무관한 확장을 동시에 여러 개 켤 수 있어야 하고(예: 아래), `_ensure_loaded()`가
나열된 순서대로 로드하므로(§2.2) 뒤 항목이 앞 항목·기본 파서를 덮어쓸 수 있다는 순서 보장이
필요하다. 각 항목은 서로의 존재를 몰라도 되는 독립된 참조라 배열 하나로 충분하다.

```yaml
ingestion:
  parser_plugins:
    - "ent_pkg.parsers.captioning:register"   # 1) 기본 등록 이후 실행 — .pdf 리더를 교체하고
                                               #    캡셔닝 post-processor를 추가
    - "ent_pkg.parsers.pptx:register"         # 2) 1)과 무관하게 .pptx를 새로 등록
```

### 2.5 기본 파서 구성

`_register_defaults()`가 `register_parser()`로 등록하는 목록. 각 리더는 기능영역별 파일로
분리되어 있다(`pipeline/steps/parser/` — `html.py`/`pdf.py`/`rst.py`/`eml.py`/`tsv.py`/`doc.py`/
`ppt.py`). LlamaIndex가 이미 동급 리더를 제공하는 포맷(csv/json/epub/xlsx/xls/pptx)은 별도
파일 없이 `registry.py`에서 바로 import & 등록한다 (US-42/US-43).

| 확장자 | 리더 | 위치 |
|---|---|---|
| `.pdf` | `PyMuPDFReader` | `parser/pdf.py` |
| `.md` | `MarkdownReader` | llama-index-readers-file |
| `.docx` | `DocxReader` | llama-index-readers-file |
| `.doc` (레거시 바이너리) | `DocReader` (`antiword` CLI 서브프로세스 — python-docx는 OOXML만 지원) | `parser/doc.py` (Dockerfile `antiword` apt 패키지 필요) |
| `.txt` | `FlatReader` | llama-index-readers-file |
| `.hwp` | `HWPReader` | llama-index-readers-hwp |
| `.html`, `.htm` | `HTMLCleanReader` | `parser/html.py` |
| `.rst` | `RstReader` (docutils 기반 — 이전 `FlatReader` raw text에서 교체) | `parser/rst.py` |
| `.eml` | `EmlReader` (stdlib `email`) | `parser/eml.py` |
| `.csv` | `CSVReader` | llama-index-readers-file |
| `.tsv` | `TsvReader` (`CSVReader`는 delimiter 고정이라 래퍼 필요) | `parser/tsv.py` |
| `.json` | `JSONReader` | llama-index-core |
| `.epub` | `EpubReader` | llama-index-readers-file (ebooklib/html2text 필요) |
| `.xlsx`, `.xls` | `PandasExcelReader` (pandas가 확장자로 엔진 자동 선택) | llama-index-readers-file (openpyxl/xlrd 필요) |
| `.pptx` | `PptxReader` | llama-index-readers-file (python-pptx 필요) |
| `.ppt` (레거시 바이너리) | `PptReader` (`olefile`로 OLE "PowerPoint Document" 스트림을 직접 스캔 — python-pptx는 OOXML만 지원) | `parser/ppt.py` (순수 Python, 시스템 바이너리 불필요) |
| `CODE_EXTENSIONS`(`.py`/`.ts`/`.tsx`/`.js`/`.jsx`/`.go`/`.java`/`.rs`/`.cpp`/`.cc`/`.c`/`.cs`/`.rb`/`.php`/`.swift`/`.kt`/`.scala`/`.sh`), `CONFIG_DATA_EXTENSIONS`(`.yaml`/`.yml`/`.properties`) | `FlatReader` (일괄) | llama-index-readers-file |

`.doc`는 이 레지스트리에서 유일하게 시스템 바이너리(파이썬 패키지가 아닌 apt 패키지)에 의존하는
리더다 — `antiword`가 없으면 `DocReader.load_data()`가 `ConfigError`를 낸다(등록 자체는 리더
인스턴스 생성만 하므로 바이너리 부재와 무관하게 항상 성공한다). `.ppt`는 원래
`catppt`(catdoc apt 패키지) 서브프로세스로 구현했었으나, 실제 Docker 이미지 빌드 + 진짜
`.ppt` 샘플로 검증한 결과 `catppt`가 exit 0인데 항상 빈 문자열을 반환하는 것으로 확인되어
(mock 테스트만으로는 못 잡아낸 결함 — [known-issues.md #22](../known-issues.md#22-ppt-레거시-파서catppt가-실제-파일에서-항상-빈-텍스트를-반환)
참고) `olefile` 기반 순수 Python 구현으로 교체했다. `antiword`는 실물 검증에서 정상 동작이
확인되어 그대로 유지한다.

`CONFIG_DATA_EXTENSIONS`도 다른 모든 확장자와 동일하게 `register_parser()`로 등록된다 — 예전엔
레지스트리에 등록하지 않고 `SimpleDirectoryReader`의 암묵적 "미등록 확장자는 raw text로 읽는다"
폴백 경로에 맡겼으나, 이 폴백은 LlamaIndex 내부 동작(버전에 따라 바뀔 수 있음)에 조용히
의존하는 것이었다. `FlatReader`로 명시 등록하면 `parser.supported_extensions()`가 실제
지원 포맷의 단일 진실 소스가 되고(`parse.py`의 `supported_extensions()`도 더 이상 별도 union이
필요 없다), `.txt`/`CODE_EXTENSIONS`와 동일하게 `filename`/`extension` 메타데이터도 함께 채워진다.

## 3. 확장 레지스터 작성 방법

새 확장 로직은 `register()` 진입점 하나를 갖는 모듈이면 된다. 이 저장소 안/밖 어디에 있어도
무방하다.

```
아무_모듈.py
├─ (선택) 커스텀 BaseReader 서브클래스        # 새/교체 리더가 필요한 경우
├─ (선택) 후처리 함수                          # list[Document] -> list[Document]
└─ register() -> None
      register_parser(ext, reader)      # 몇 번이든 — 있으면 교체, 없으면 추가
      unregister_parser(ext)            # 몇 번이든 — 특정 확장자 제거
      register_post_processor(fn)       # 몇 번이든 — 파싱 후 공통 처리 추가
```

절차:

1. 리더 또는 후처리 함수를 준비한다.
2. 위 구조로 `register()`를 작성한다 — 한 모듈에 여러 확장자를 몰아 넣어도, 목적별로 모듈을
   나눠도 무방하다(§2.3 API는 이를 구분하지 않는다).
3. `ingestion.parser_plugins`에 `"모듈경로:register"`를 추가한다.

`parse.py`를 포함한 기존 코드는 이 과정에서 수정하지 않는다 — `_register_defaults()`가 먼저
실행된 뒤 이 목록이 순서대로 실행되므로(§2.2), 여기서 부른 `register_parser`/`unregister_parser`가
기본 파서를 그대로 덮어쓰거나 제거한다.

## 4. 참조 대상 코드

- 레지스트리 엔진: `pipeline/steps/parser/registry.py` (등록 API), `pipeline/steps/parser/__init__.py`
  (공개 API re-export)
- `pipeline/steps/parse.py`는 Op 계약 함수(`parse`/`parse_local`/`supported_extensions`/
  `_extract_doc_created_at`)만 남기고 리더 클래스/확장자 상수는 갖지 않는다 (US-42)
- 사용처: `connectors/confluence.py:294`, `connectors/github.py:103` (둘 다
  `pipeline.steps.parse.supported_extensions()`를 그대로 호출 — 위치 이동에 영향 없음)

## 5. 검토한 대안

| 대안 | 기각 이유 |
|---|---|
| 정적 딕셔너리 유지, 필요 시 `parse.py` 직접 수정 | 저장소 밖 구현체·배포별 구성 차이를 못 다룸 |
| 애플리케이션 startup 훅에서 등록 | `parse()` 진입점이 여러 개 — 특정 프레임워크에 못 묶음 |
| 패키지 메타데이터 자동 탐색(entry_points) | 활성화 여부가 설정 파일에 안 보임 (하드룰 1: `get_settings()` 단일 소스 원칙과 불일치) |
| 기본 파서를 특권 경로로 분리, 추가 파서만 레지스트리화 | 교체/제거 시 기본 파서 쪽 예외 처리가 항상 필요해짐 |
