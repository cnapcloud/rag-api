# US-43: 레거시 .doc/.ppt + .pptx 지원 추가

**상태**: done

> 설계: [parser-registry.md](../../../docs/internal/design/parser-registry.md) (등록 API는
> US-41에서 확정, 패키지 구조는 US-42에서 확정 — 이 US는 그 위에 리더 3종을 추가한다)

## 목적

MS Word/PowerPoint 문서 지원이 `.docx`(신형)만 있고 `.doc`(구형 바이너리), PowerPoint 전체
(`.ppt`/`.pptx`)가 빠져 있다. `python-docx`/`python-pptx`는 OOXML(신형) 컨테이너만 읽을 수
있어 구형 OLE 바이너리 포맷(`.doc`/`.ppt`)은 순수 pip 패키지로 처리할 수 없다 — 시스템
바이너리(`antiword`, `catdoc` 패키지의 `catppt`)로 텍스트를 추출해야 한다.

## 범위

- `pyproject.toml`에 `python-pptx` 추가 (`.pptx`는 LlamaIndex `PptxReader`가 그대로 사용,
  순수 pip 의존성).
- `Dockerfile`(빌드 대상은 이 파일 하나뿐 — `Dockerfile.dagster`/k8s dagster Dockerfile은
  `build-push.yml` 트리거 경로에 없고 `src/`도 COPY하지 않아 우리 파싱 코드를 실행하지
  않음)에 `antiword`(.doc), `catdoc`(.ppt — `catppt` 바이너리 제공) apt 패키지 추가.
- `pipeline/steps/parser/doc.py` 신규 — `DocReader(BaseReader)`, `subprocess.run(["antiword",
  file])`로 텍스트 추출. 바이너리 미설치(`FileNotFoundError`) -> `ConfigError`, 파싱 실패
  (non-zero exit) -> `IngestValidationError`.
- `pipeline/steps/parser/ppt.py` 신규 — 최초 구현은 `PptReader(BaseReader)`가 `catppt` 서브프로세스를
  썼으나, 실물 검증(2026-07-16, 아래 "후속 수정" 참고)에서 실제 파일마다 빈 텍스트만 반환하는
  결함이 발견되어 `olefile` 기반 순수 Python 구현으로 교체됐다 — 최종 구현은 시스템 바이너리를
  쓰지 않는다.
- `.pptx`는 별도 파일 없이 `registry.py`에서 LlamaIndex `PptxReader` 바로 등록(csv/json/epub/
  xlsx/xls와 동일 패턴 — US-42 §패키지 구조 참고).
- `pipeline/steps/parser/extensions.py`의 `DOCUMENT_EXTENSIONS`에 `.doc`/`.ppt`/`.pptx` 추가.
- `pipeline/steps/parser/registry.py`의 `_register_defaults()`에 세 확장자 등록 추가.
- 테스트: `DocReader`는 `subprocess.run`을 mock해 stdout/exit code 시나리오(성공/파싱 실패/
  바이너리 없음) 검증 — CI 환경에 antiword 설치를 전제하지 않는다. `PptReader`는 최초엔
  `DocReader`와 동일하게 mock 테스트만 있었으나, 후속 수정에서 실제 `.ppt` 바이너리 픽스처
  기반 테스트로 교체됐다(아래 참고). `.pptx`는 `python-pptx`로 실제 샘플 파일을 만들어
  end-to-end 검증(다른 신형 포맷과 동일).

## 비범위

- `.doc`/`.ppt`를 `unstructured`/LibreOffice 기반으로 처리하는 방식 — 더 높은 충실도를 주지만
  Docker 이미지에 LibreOffice 전체를 넣어야 해서 빌드 크기/시간이 크게 늘어난다. antiword(.doc)와
  olefile(.ppt, 후속 수정으로 catppt 대체) 모두 이보다 훨씬 가벼워 이 트레이드오프에서 제외.
- `.doc`/`.ppt` 서식(표/이미지/도형) 보존 — antiword/olefile 모두 순수 텍스트만 추출한다. 표는
  탭/공백으로 근사될 뿐 구조화되지 않음 (기존 `.xlsx`→`PandasExcelReader`처럼 구조를 보존하는
  수준은 기대하지 않는다).
- `Dockerfile.dagster`/k8s dagster Dockerfile 수정 — 위 목적 문단 참고, 우리 파싱 코드를 실행하지
  않는 이미지라 대상 아님.

## 완료 기준

- [x] `.doc` 샘플에서 antiword 성공 시나리오 mock으로 텍스트 추출 확인
- [x] `.doc` antiword 비정상 종료(exit != 0) 시 `IngestValidationError` 발생 확인
- [x] antiword 바이너리 부재(`FileNotFoundError`) 시 `ConfigError` 발생 확인 (`.ppt`/`catppt`도
      동일 패턴으로 확인)
- [x] `.ppt` 샘플에서 catppt 성공 시나리오 mock으로 텍스트 추출 확인
- [x] `.pptx` 샘플(python-pptx로 생성)이 실제로 파싱되어 슬라이드 텍스트가 추출됨을 확인
      (실제 라이브러리로 end-to-end 검증, mock 아님)
- [x] `supported_extensions()`에 `.doc`/`.ppt`/`.pptx` 포함 확인 (총 36개 확장자로 확인됨)
- [x] (최초 구현 당시, 이후 무효화됨 — 아래 "후속 수정" 참고) `Dockerfile`에 `antiword`/`catdoc`
      apt 설치 라인 반영
- [x] 기존 회귀 테스트 전체 통과(502 passed / 2 skipped), `ruff` 통과
- [x] (후속 추가) `_extract_doc_created_at()`에 `.pptx` 분기 추가 — `python-pptx`의
      `Presentation(file).core_properties.created`, `.docx`와 동일 패턴. `.doc`/`.ppt`는 OLE
      바이너리라 이 메타데이터 자체가 없어 대상에서 제외(S3 LastModified로 폴백)
- [x] (후속 수정, 2026-07-16) 아래 "오픈 이슈"에서 보류하기로 했던 실물 검증을 실제로 수행 —
      로컬에서 프로덕션 `Dockerfile`을 빌드하고 진짜 레거시 `.doc`/`.ppt` 샘플로 검증. `antiword`는
      정상 동작 확인, `catppt`는 세 가지 생성 경로 모두에서 exit 0인데 항상 빈 문자열을 반환하는
      결함을 발견(mock 테스트로는 못 잡음). `PptReader`를 `olefile` 기반 순수 Python 구현으로
      교체하고 `Dockerfile`에서 `catdoc` 제거(`antiword`만 유지). 상세는
      [known-issues.md #22](../../../docs/internal/known-issues.md#22-ppt-레거시-파서catppt가-실제-파일에서-항상-빈-텍스트를-반환)
      (resolved) 참고. 테스트도 subprocess mock에서 실제 `.ppt` 바이너리 픽스처
      (`tests/unit/fixtures/sample.ppt`) 기반으로 교체

## 의존성

- US-42 — `pipeline/steps/parser/` 패키지 구조(기능영역별 파일 분리 컨벤션)가 먼저 있어야 함 (done).

## 오픈 이슈

없음 — 아래는 최초 작성 당시의 오픈 이슈였으나 2026-07-16 실물 검증을 실제로 수행해 해결됨(위
"후속 수정" 항목 참고). 기록으로 남겨둔다.

- ~~**antiword/catdoc 실물 검증 공백 (결정: 보류)**: `DocReader`/`PptReader` 테스트는
  `subprocess.run`을 mock하므로 antiword/catdoc 바이너리가 실제 `.doc`/`.ppt` 파일을 제대로
  파싱하는지는 로컬에서도 CI에서도 검증된 적이 없다. ... antiword/catdoc이 오래되고 안정적인
  패키지라 위험도가 낮다고 보고 실물 검증(CI smoke test 등) 추가는 보류하기로 결정 — 필요해지면
  별도 작업으로.~~ → 실제로 검증해보니 `catppt` 쪽 판단이 틀렸음이 확인됨.
