# US-45: KB 설정 오버라이드 필드 스키마 — 값 검증/description/override 메타데이터 + `/settings/schema`

**상태**: done

> 설계: [kb-settings-override-schema.md](../../../docs/internal/design/kb-settings-override-schema.md)

## 목적

US-44(`kb-settings-override.md`)는 KB 설정 오버라이드의 저장/적용 메커니즘(리졸버·저장 스키마·
REST API)만 만들었고, `Settings`의 개별 필드 자체는 손대지 않았다. 그 결과 override 저장 시
타입만 검증되고 값의 의미상 범위(예: `jaccard_threshold: 5.0`)는 걸러지지 않으며, 필드
description이 없어 rag-admin이 폼 라벨을 하드코딩해야 하고, override 허용 여부가
`EXCLUDED_OVERRIDE_KEYS`라는 필드 선언과 분리된 frozenset에 있어 새 필드 추가 시 배제 처리를
깜빡하면 조용히 오버라이드 가능해지는 드리프트 위험이 있다. 이 세 가지(값 검증/description/
override 허용 여부)를 필드 선언 옆으로 옮기고, 그 결과를 그대로 노출하는
`GET /kb/{kb_id}/settings/schema` 엔드포인트를 만든다.

## 범위

- `rag_api/config/settings.py`의 override 대상 필드(설계 문서 §2.1) 전부에
  `Field(ge=, le=, description=...)` 추가.
- `chunking.strategy`를 `str` 대신 `pipeline/steps/chunk.py`의
  `ChunkStrategy = Literal["recursive", "semantic"]`를 재사용하도록 승격(설계 문서 §4.1).
- `EXCLUDED_OVERRIDE_KEYS` frozenset 제거. 배제 대상 필드(`parser_plugins`,
  `dedup.simhash.ngram`/`num_bands`/`simhash_bits`, `dedup.minhash.user_words_path`)에
  `json_schema_extra={"override": False}` 적용.
- `validate_override_key` 갱신 — `OVERRIDABLE_SETTINGS_PREFIXES` allow-list는 그대로 두고,
  기존에 별도 단계였던 deny-list(`EXCLUDED_OVERRIDE_KEYS`) 조회를 필드 경로 존재 확인용
  `model_fields` 순회의 리프 필드에서 `override` 플래그를 함께 확인하는 방식으로 통합(설계
  문서 §4 코드 예시).
- `GET /kb/{kb_id}/settings/schema` 엔드포인트 신규 구현(`api/routers/kb.py`) — dot-key별
  `type`/`enum`/`default`/`overridable`/`min`/`max`/`description`/소속 그룹을 응답.
  `dedup.simhash.hamming_identical_threshold`/`hamming_similar_threshold`는 정적
  `Field(le=)` 대신 응답 직렬화 시점에 `get_settings().dedup.simhash.simhash_bits`를 조회해
  `max`를 계산하는 특별 처리 포함(설계 문서 §5).
- base 문서(`kb-settings-override.md`) §9에 새 라우트 추가, §5 표를 필드 메타데이터 기준으로
  갱신.

## 비범위

- **cross-field 검증**(설계 문서 §3 — `chunk_overlap < chunk_size` 등 5건, `model_validator`
  필요)은 이번 US에서 다루지 않는다. 저장 시점 에러를 어느 dot-key에 붙일지가 rag-admin과 별도
  조율이 필요해 범위가 다르다 — 별도 US로 분리.
- **rag-ent-api 쪽 반영**(`ImageCaptioningSettings`/`PdfOcrFallbackSettings`/
  `TableLayoutSettings`에 동일한 `Field(ge=, le=, description=...)` + `ENT_EXCLUDED_OVERRIDE_KEYS`
  제거, 설계 문서 §2.2)은 rag-ent-api 저장소의 별도 backlog로 만든다(US-44 때 E-25가 그랬듯) —
  이 리포지토리 소스는 건드리지 않는다.
- **rag-admin Configuration 페이지 실제 구현**(`kb-settings-override-ui.md`)은 rag-admin
  저장소의 별도 backlog.
- `dedup.minhash.title_only_min_jaccard_floor`와 `jaccard_threshold`의 관계, RapidOCR
  `pdf_ocr_fallback.language` enum 목록 확정 — 설계 문서 §2.1/§2.2에 미확정으로 표시된 항목은
  이번 US에서 강제로 결정하지 않고 현재 타입(제약 없는 float/str) 그대로 둔다.

## 완료 기준

- [x] 설계 문서 §2.1 표의 override 대상 필드 전부에 `Field(ge=, le=, description=...)` 적용
- [x] `chunking.strategy`가 `chunk.py`의 `ChunkStrategy`를 재사용(`Literal["recursive",
      "semantic"]`)
- [x] `EXCLUDED_OVERRIDE_KEYS` frozenset 삭제, 배제 대상 필드가
      `json_schema_extra={"override": False}`로 표시됨
- [x] `validate_override_key`가 allow-list + 통합된 `model_fields` 순회만으로 동작(별도
      deny-list 조회 없음)
- [x] `GET /kb/{kb_id}/settings/schema` 구현 — ingestion/chunking/dedup 서브트리 순회, 응답에
      `type`/`enum`/`default`/`overridable`/`min`/`max`/`description`/그룹 포함
- [x] `hamming_identical_threshold`/`hamming_similar_threshold`의 `max`가 그 배포의 실제
      `simhash_bits` 값으로 계산됨(정적 상수 아님) — `simhash_bits`를 다르게 설정한 케이스로
      테스트. 구현 중 사용자 지시로 두 필드 모두 `le=19` 저장 시점 sanity cap도 추가(표시용
      동적 max와는 별개 — kb-settings-override-schema.md §2.1 갱신 참고)
- [x] 범위 밖 값(예: `dedup.minhash.jaccard_threshold: 5.0`)으로 override 저장 시도 시 422
      응답 — `validate_override_values` 신규 추가(설계 문서엔 명시 안 됐으나 이 완료 기준을
      만족시키기 위해 저장 시점 재검증 경로가 필요해 추가)
- [x] 배제 필드(예: `ingestion.parser_plugins`) override 저장 시도 시 여전히 거부됨(회귀 없음)
- [x] 관련 테스트 전체 통과 — 564 passed, 2 skipped(기존 skip 유지), ruff/mypy clean

## 의존성

- US-44 — KB별 설정 오버라이드 기반(리졸버·저장 스키마·REST API·`validate_override_key`)이
  선행 완료되어 있어야 그 위에 필드 메타데이터를 얹을 수 있음.

## 후속 수정 (2026-07-19, rag-ent-api E-26 착수 중 발견)

`describe_overridable_settings`가 top-level 섹션 클래스를 모듈의 `Settings.model_fields[section]`에서
가져와, rag-ent-api처럼 `Settings`를 상속해 `ingestion`을 확장 서브클래스로 재선언한 배포에서
`image_captioning`/`pdf_ocr_fallback`/`table_layout` 같은 확장 필드가 스키마에서 누락되는 버그가
있었다 — `resolve_settings()`가 이미 `type(base)`를 쓰는 것과 같은 이유로 `type(current)`를
쓰도록 수정(`test_describe_overridable_settings_walks_subclass_extended_sections` 추가).
