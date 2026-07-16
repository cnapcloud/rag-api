# US-42: 파서 패키지 구조화 + 신규 포맷 8종 지원 (CSV/TSV/JSON/EPUB/XLSX/XLS/RST/EML)

**상태**: done

> 설계: [parser-registry.md](../../../docs/internal/design/parser-registry.md) (등록 API/데이터
> 흐름은 US-41에서 확정 — 이 US는 그 위에서 파일 배치를 재구성하고 리더 8종을 추가한다)

## 목적

`pipeline/ops/parse.py`에 리더 클래스(`HTMLCleanReader`, `PyMuPDFReader`)와 확장자 상수
(`DOCUMENT_EXTENSIONS`/`CODE_EXTENSIONS`/`CONFIG_DATA_EXTENSIONS`/`CODE_LANGUAGE_MAP`)가 Op
계약 함수(`parse`/`parse_local`)와 한 파일에 뒤섞여 있고, US-41에서 추가된 등록 엔진도
`pipeline/ops/parser_registry.py`라는 별도 최상위 모듈로 떨어져 있다. 지원 포맷을 8종 늘리는
이번 작업을 계기로 기능영역별 파일로 분리된 `pipeline/ops/parser/` 패키지로 재구성한다.

[R2R의 structured 파서 목록](https://github.com/SciPhi-AI/R2R/tree/main/py/core/parsers/structured)을
검토한 결과 — CSV/JSON/EPUB/XLSX/XLS는 LlamaIndex가 이미 동급 이상 리더를 갖고 있어 R2R 코드를
포팅할 필요가 없고(등록만 하면 됨), TSV/RST/EML은 대응 리더가 없거나(TSV) 개선 여지가
있어(RST) 신규로 작성한다.

## 범위

### 패키지 구조

```
pipeline/ops/parser/
├── __init__.py       # 공개 API re-export — register_parser/unregister_parser/
│                      #   register_post_processor/get_parsers/get_post_processors/
│                      #   supported_extensions/reset_registry (구 parser_registry.py 대체)
├── registry.py        # 등록 엔진 이동 — _ensure_loaded()/_register_defaults()/_load_plugins()
│                      #   (구 parser_registry.py 본문, 로직 변경 없음)
├── extensions.py       # DOCUMENT_EXTENSIONS/CODE_EXTENSIONS/CONFIG_DATA_EXTENSIONS/
│                      #   CODE_LANGUAGE_MAP — 리더 클래스에 의존하지 않는 순수 데이터라 분리
│                      #   (chunk.py/dedup/__init__.py가 리더 import 없이 상수만 참조하게 됨)
├── html.py             # HTMLCleanReader 이동 (trafilatura 기반, 변경 없음)
├── pdf.py               # PyMuPDFReader 이동 (변경 없음)
├── rst.py               # RstReader 신규 — docutils.core.publish_string으로 HTML 변환 후
│                      #   태그 제거 (R2R rst_parser.py 방식 참고, DB/LLM provider 등 R2R
│                      #   고유 구조는 가져오지 않고 BaseReader.load_data() 하나로 단순화).
│                      #   기존 FlatReader()(raw text) 대체
├── eml.py               # EmlReader 신규 — stdlib email 모듈로 Subject/From/To/Date 메타 +
│                      #   text/plain 본문 추출 (R2R eml_parser.py 방식 참고, 외부 의존성 없음)
└── tsv.py               # TsvReader 신규 — csv 모듈 delimiter="\t" (LlamaIndex CSVReader는
                         #   delimiter 인자가 없어 그대로 재사용 불가, 20줄 내외 래퍼)
```

CSV/JSON/EPUB/XLSX/XLS는 별도 파일을 만들지 않는다 — LlamaIndex 기존 리더를 `registry.py`의
`_register_defaults()`에서 바로 import & 등록하는 한 줄짜리 작업이라, 파일을 쪼개면 오히려
탐색 비용만 늘어난다.

| 확장자 | 리더 | 비고 |
|---|---|---|
| `.csv` | `llama_index.readers.file.CSVReader` | 그대로 등록 |
| `.tsv` | `parser.tsv.TsvReader` (신규) | CSVReader delimiter 고정이라 래퍼 필요 |
| `.json` | `llama_index.core.readers.json.JSONReader` | 그대로 등록 |
| `.epub` | `llama_index.readers.file.EpubReader` | `ebooklib`+`html2text` 의존성 필요 (둘 다 없으면 ImportError) |
| `.xlsx` | `llama_index.readers.file.PandasExcelReader` | `openpyxl` 의존성 필요 |
| `.xls` | `llama_index.readers.file.PandasExcelReader` | 위 + `xlrd` 의존성 필요 (pandas가 확장자로 엔진 자동 선택) |
| `.rst` | `parser.rst.RstReader` (신규) | 기존 `FlatReader()` 대체 |
| `.eml` | `parser.eml.EmlReader` (신규) | 신규 확장자 |

### 코드 변경

- `parse.py`는 Op 계약 함수(`parse`/`parse_local`/`supported_extensions`/
  `_extract_doc_created_at`)만 남기고 위 패키지에서 import.
- 구 모듈 `pipeline/ops/parser_registry.py` 삭제. 아래 참조 전부
  `rag_api.pipeline.ops.parser`(또는 `.registry`/`.extensions`)로 갱신:
  `connectors/confluence.py`, `connectors/github.py`, `pipeline/ops/chunk.py`,
  `pipeline/ops/dedup/__init__.py`, `pipeline/runner.py`, `defs/ops/ingest_ops.py`,
  `defs/ops/dedup_ops.py`, `config/settings.py`(주석).
- `extensions.py`의 `DOCUMENT_EXTENSIONS`에 `.csv`/`.tsv`/`.json`/`.epub`/`.xlsx`/`.xls`/`.eml`
  추가 (`.rst`는 기존 유지, 리더만 교체).
- `pyproject.toml`에 의존성 추가: `docutils`(rst), `openpyxl`(xlsx), `xlrd`(xls), `ebooklib`+
  `html2text`(epub — `EpubReader`가 둘 다 요구). `eml`/`tsv`/`json`은 stdlib/기존 LlamaIndex
  core만 사용 — 추가 의존성 없음.
- 테스트 import 경로 갱신: `test_confluence_connector.py`, `test_github_connector.py`,
  `test_parser_registry.py`, `test_parse.py`, `test_parse_html.py`, `test_doc_created_at.py`,
  `tests/integration/test_ingest_pipeline.py`, `tests/unit/fixtures/fake_parser_plugin.py`.
- 신규 포맷 8종 각각 최소 1개 이상의 샘플 파일 기반 단위 테스트 추가 (파일 단위는 구현 시
  기존 명명 규칙 확인 후 결정 — 오픈 이슈 참고).

## 비범위

- org/msg/p7s 등 R2R의 나머지 구조화 포맷 — 이 저장소 소스(Confluence/GitHub/S3 업로드)에서
  실사용 수요가 없어 지금은 추가하지 않는다. 필요해지면 별도 US.
- 등록 엔진(레지스트리 API/지연 로더/플러그인 로딩 방식) 자체의 변경 — US-41에서 이미 확정된
  설계를 그대로 옮기기만 한다.
- `parser_plugins` 설정 스키마 변경 — 없음.
- XLSX/XLS의 "연결된 셀 그룹 단위 분할"(R2R `XLSXParserAdvanced`의 connected-components 로직)
  — 우리 청킹 파이프라인엔 과한 기능이라 `PandasExcelReader` 기본 동작(행 단위 텍스트화)만 쓴다.

## 완료 기준

- [x] `pipeline/ops/parser/` 패키지가 생성되고 `pipeline/ops/parser_registry.py`는 삭제됨
- [x] `grep -rn "pipeline\.ops\.parser_registry" src/ tests/` 결과 0건
- [x] `_register_defaults()`가 기존 8개 리더 + 신규 8개 리더(csv/tsv/json/epub/xlsx/xls/eml,
      rst는 교체)를 정상 등록함을 `supported_extensions()`로 확인 (기존 대비 +7 확장자, 총 33개
      확장자로 확인됨)
- [x] `.rst` 샘플 파일 파싱 시 RST 마크업(`====` 밑줄, `.. code-block::` 지시자 등)이 결과
      텍스트에 남지 않음을 테스트로 확인 (기존 `FlatReader` 대비 개선 검증) —
      `test_parse_formats.py::TestRstReader`. 구현 중 `publish_string()`(R2R과 동일 방식)을
      쓰면 docutils 기본 CSS가 `<style>`로 통째로 섞여 들어가는 문제를 발견해
      `publish_parts()`의 `body`/`title` 파트만 쓰는 방식으로 수정 (R2R 원본 그대로 포팅했다면
      재현됐을 결함)
- [x] `.eml` 샘플 파일 파싱 시 Subject/From/To/Date 메타데이터와 본문 텍스트가 모두 추출됨을
      테스트로 확인 — `TestEmlReader`
- [x] `.tsv` 샘플 파일이 탭 구분으로 정확히 파싱됨을 테스트로 확인 (쉼표가 포함된 셀 값이
      깨지지 않는 경우 포함) — `TestTsvReader`
- [x] `.csv`/`.json`/`.epub`/`.xlsx`/`.xls` 각각 샘플 파일 파싱이 정상 동작함을 테스트로 확인 —
      `TestBuiltinFormatRegistration` (`.xls`는 `tests/unit/fixtures/sample.xls` 고정 픽스처 사용)
- [x] `chunk.py`/`dedup/__init__.py`가 `extensions.py`만 import하고 리더 클래스에는 의존하지
      않음을 확인 (import 순환/불필요 의존 없음)
- [x] 기존 회귀 테스트(parse/parser_registry/html/confluence/github/doc_created_at/
      ingest_pipeline) 전체 통과 — import 경로만 바뀌고 동작은 동일함을 확인 (unit 456 passed,
      전체 491 passed / 2 skipped)
- [x] `ruff` 통과 (라인 길이/import 정렬 포함)

## 의존성

- US-41 — 등록 엔진(`register_parser`/`_ensure_loaded`/`_register_defaults` 등) 골격이 먼저
  있어야 그 파일을 패키지로 옮기는 작업이 성립한다 (done).

## 오픈 이슈

- **커넥터 노이즈 (결정: 이번 US 범위에서는 수용)**: `confluence.py`/`github.py`는
  `supported_extensions()`로 다운로드 대상을 거른다 (`confluence.py:294`, `github.py:103`).
  `.json`/`.csv`/`.xlsx` 등이 전역으로 지원되면 GitHub 저장소의 `package.json`/lock 파일 등도
  자동으로 인제스트 대상이 된다. 확인 결과 GitHub/Confluence 커넥터에는 `exclude_patterns` 같은
  글롭 제외 설정이 원래 없다(`path_prefix`만 존재, web 커넥터에만 `exclude_patterns` 있음) —
  즉 이미 `CODE_EXTENSIONS` 전체(.py/.go/.java/...)가 필터 없이 저장소 전체에서 무차별
  수집되는 기존 동작과 같은 성격의 트레이드오프이며 이번 US가 새로 만드는 문제가 아니다.
  커넥터별 exclude 설정 추가는 범위가 커서 별도 US로 분리하고, 이번 US는 포맷 지원까지만 한다.
- 신규 리더 테스트를 포맷별 파일로 쪼갤지(`test_parse_rst.py`/`test_parse_eml.py`/...), 기존
  `test_parse.py`/`test_parse_html.py`처럼 유지할지는 구현 시 기존 테스트 파일 명명 규칙을
  보고 결정한다. → 구현 결정: 신규 포맷은 `test_parse_formats.py` 하나로 통합(리더가 작아 개별
  파일은 과함), HTML은 기존 `test_parse_html.py` 유지.
