# US-44: KB별 설정 오버라이드 (ingestion/chunking/dedup)

**상태**: in-progress

> 설계: [kb-settings-override.md](../../../docs/internal/design/kb-settings-override.md)

## 목적

`settings.yaml`의 `ingestion`/`chunking`/`dedup` 값은 지금 프로세스 전체에 적용되는 단일 설정이라,
KB마다 다른 파싱/청킹/dedup 정책이 필요하면 KB별로 별도 배포를 띄우는 수밖에 없다. KB 단위로
값을 오버라이드하고 없으면 전역 값으로 폴백하는 구조를 추가해 이 제약을 없앤다.

## 범위

- `config/settings.py`: `resolve_settings(kb_id)` 리졸버, `_apply_dotted_overrides`,
  `_validate_override_key`(allow-list `ingestion.`/`chunking.`/`dedup.` + deny-list) 추가
- `migrations/002_kb_settings_overrides.sql`: `kb_settings_overrides` 테이블
  (`kb_id`, `key`, `value JSONB`, `updated_at`, `PRIMARY KEY (kb_id, key)`)
- `infra/postgres.py`: `get_kb_settings_overrides` / `upsert_kb_settings_override` /
  `delete_kb_settings_override` / `replace_kb_settings_overrides` / `clear_kb_settings_overrides`
- `api/routers/kb.py`: `GET /kb/{kb_id}/settings`(범위 제한된 유효 설정),
  `GET/PUT/PATCH/DELETE /kb/{kb_id}/settings/overrides`
- `pipeline/steps/parser/registry.py`: `PostProcessor` 타입에 `kb_id: str | None` 파라미터 추가
- `pipeline/steps/parse.py`: `parse()` 시그니처에 `kb_id` 추가, `SimpleDirectoryReader`에
  `file_metadata` 배관, post-processor 호출부에 kb_id 전달
- `pipeline/steps/chunk.py`: `chunk()`가 kb_id를 받아 `resolve_settings(kb_id).chunking` 사용
  (지금 내부에서 직접 읽는 `min_chunk_chars`/`semantic_threshold`/`code_chunk_lines*` 포함)
- `pipeline/steps/validate.py`: `max_file_size_mb`/`min_content_chars`/`html_extraction_policy`를
  `resolve_settings(kb_id)` 기반으로 교체
- `pipeline/steps/dedup/*`: `get_settings()` → `resolve_settings(kb_id)` 교체(kb_id는 이미 호출부에 있음)
- `pipeline/runner.py`, `defs/ops/ingest_ops.py`(`chunk_op` 등 kb_id 미배관 지점): kb_id 배관
- `docs/internal/design/parser-registry.md`: `PostProcessor` 계약 변경 반영

## 비범위

- rag-ent-api 쪽 플러그인 변경(`image_ocr.py`/`table_layout.py`의 등록 무조건화,
  `caption_embedded_images`/`extract_tables`/리더 내부 `get_settings()` 교체) — 다른 저장소이며
  design 문서 §8 참고. 이 US가 rag-api 쪽 기반을 완료한 뒤 rag-ent-api에서 별도로 진행.
- `ingestion.parser_plugins`, `dedup.simhash.ngram`/`num_bands`/`simhash_bits`,
  `dedup.minhash.user_words_path` 오버라이드 — 설계상 배제 대상(design 문서 §5), deny-list로
  명시적으로 막아둔다.
- KB 오버라이드 변경 이력/감사 로그 UI — 필요해지면 별도 US.

## 완료 기준

- [x] `resolve_settings(kb_id)` 유닛 테스트 — override 없음 / 부분 override / 전체 override
      (`tests/unit/test_settings.py`)
- [x] `validate_override_key` 유닛 테스트 — allow-list 밖 키 거부(`provider.*`/`redis.*` 등),
      deny-list 키 거부, 존재하지 않는 필드 거부, 스칼라 필드를 더 파고드는 잘못된 중첩 경로 거부
      (`tests/unit/test_settings.py`)
- [ ] `kb_settings_overrides` 마이그레이션 적용 및 `run_migrations()` idempotent 확인 — SQL 작성/
      `infra/postgres.py` CRUD 유닛 테스트(`tests/unit/test_postgres_crud.py`)까지 완료, 실제 DB
      적용 확인은 배포 환경에서(하드룰 #3 — 유닛 테스트에서 실제 Postgres 연결 금지)
- [x] REST API 통합 테스트 — `GET /settings`, `GET/PUT/PATCH/DELETE /settings/overrides` 전부
      (`tests/unit/test_kb_settings_api.py`)
- [x] `GET /kb/{kb_id}/settings` 응답에 `provider`/`redis`/`postgres`/`qdrant` 등 비대상 섹션이
      없는지 확인(보안 회귀 테스트) — `test_returns_only_ingestion_chunking_dedup_sections`
- [x] PATCH로 서로 다른 키를 동시에 갱신해도 lost update 없이 둘 다 반영되는지 확인 —
      `upsert_kb_settings_override`/`delete_kb_settings_override`(`infra/postgres.py`)에
      read step이 아예 없음(단일 `INSERT ... ON CONFLICT DO UPDATE`/`DELETE` 문 하나뿐, 코드
      확인으로 검증 — lost update는 "읽고 → 메모리에서 고치고 → 다시 쓰기" 사이 경합 창이
      있어야 발생하는데 그 창 자체가 코드에 없어 구조적으로 불가능. 라이브 동시성 테스트는
      이후 코드가 read-modify-write로 바뀌는 회귀를 못 잡는다는 점에서 이 코드 확인보다
      약한 보장이라 불필요)
- [x] `parse()`/`chunk()`/dedup 스텝이 kb_id 기반 override를 실제로 반영하는지 통합 테스트
      (`test_chunk_applies_kb_scoped_min_chunk_chars_override`,
      `test_validate_applies_kb_scoped_max_file_size_override`)
- [x] 기존 전체 테스트 스위트 통과(회귀 없음) — 549 passed, ruff/mypy clean

## 의존성

없음

## 오픈 이슈

- rag-ent-api 쪽 후속 작업(design 문서 §8) 착수 시점은 이 US 완료 후 별도로 정한다.
- 마이그레이션 실제 적용 확인은 유닛 테스트 범위를 벗어남(실 Postgres 필요, 하드룰 #3) —
  배포/스테이징 환경에서 `run_migrations()` 정상 동작만 확인하면 됨(SQL 자체는 001과 동일한
  `CREATE TABLE IF NOT EXISTS` 패턴이라 리스크 낮음).
