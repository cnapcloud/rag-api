# US-41: 파서 확장 레지스트리

**상태**: done

> 설계: [parser-registry.md](../../../docs/internal/design/parser-registry.md)

## 목적

`pipeline/ops/parse.py`의 확장자 -> 리더 매핑이 정적 딕셔너리(`_get_file_extractor()`)라서 새
포맷을 지원하거나 기존 리더를 교체/제거하려면 `parse.py` 자체를 고쳐야 한다. 등록(registration)
기반 레지스트리로 바꿔, `parse.py`를 고치지 않고도 파서를 추가·교체·제거할 수 있게 한다.

## 범위

design 문서 §2~§3에 상세가 있으므로 여기서는 목록만 나열한다.

- `pipeline/ops/parser_registry.py` 신규 — `register_parser()`/`unregister_parser()`/
  `register_post_processor()`/`get_parsers()`/`get_post_processors()`/`supported_extensions()`,
  지연 로더(`_ensure_loaded()`), 기본 파서 로더(`_register_defaults()`), 설정 기반 플러그인
  로더(`_load_plugins()`)
- `pipeline/ops/parse.py` — `_get_file_extractor()` 제거, `parse()`가 레지스트리에서 파서를
  조회하도록 변경. 정적 상수 `SUPPORTED_EXTENSIONS`를 `supported_extensions()` 함수로 교체
  (레지스트리 등록 확장자 + `CONFIG_DATA_EXTENSIONS` 합집합). `reader.load_data()` 이후 등록된
  post-processor를 순차 적용해 문서 목록에 병합하는 지점 추가(현재는 등록된 post-processor 없음
  — 배선만 완료)
- `connectors/confluence.py`, `connectors/github.py` — `SUPPORTED_EXTENSIONS` import를
  `supported_extensions()` 호출로 변경
- `config/settings.py`의 `IngestionSettings`에 `parser_plugins: list[str] = []` 필드 추가
- `settings.yaml`, `docker/settings.yaml`, k8s configmap 3곳에 `ingestion.parser_plugins: []`
  추가

## 비범위

- 실제 확장 파서 구현(이미지 캡셔닝, PDF OCR 폴백, PPT 등)은 이 US 범위 밖 — US-40 및 향후
  별도 US/외부 저장소에서 다룬다. 이 US는 레지스트리 골격만 제공한다.
- entry_points 기반 자동 탐색 (design 문서 §5에서 기각)
- 런타임 hot reload — 등록은 프로세스 내 최초 1회로 고정 (design 문서 §3, 비목표)

## 완료 기준

- [x] `parser_plugins: []`(기본값)에서 기존 파싱 동작이 완전히 동일함을 확인 (회귀 없음)
- [x] 테스트에서 임의 `register()` 함수로 새 확장자 등록 시 `supported_extensions()`가 이를
      인식함을 확인
- [x] 같은 확장자에 재등록 시 기존 리더가 교체됨을 확인
- [x] `unregister_parser()`로 뺀 확장자가 `supported_extensions()`에서 사라짐을 확인
- [x] `register_post_processor()`로 등록한 함수가 `parse()` 결과에 반영됨을 확인
- [x] `_register_defaults()`가 기존 8개 리더(pdf/md/docx/txt/hwp/html/htm/rst) + CODE_EXTENSIONS를
      그대로 등록함을 확인
- [x] `parser_plugins`에 잘못된 형식의 항목(`"module.path:func"` 형식이 아님)을 넣으면
      `ConfigError`가 발생함을 확인
- [x] 관련 테스트(`tests/unit/test_parser_registry.py` 신규, 기존 `test_parse_html.py`,
      `test_confluence_connector.py`, `test_github_connector.py`) 전체 통과

## 의존성

없음.

## 오픈 이슈

없음 — `docs/internal/design/image-ocr-parsing.md`(US-40)는 이 레지스트리 API를 쓰도록 §2/§6/§7/§9
갱신 완료(설정 스키마 §5는 그대로 유지).
