# US-10 — 문서 생성일자 메타데이터 저장 및 reindex 큐 정렬

## 개요

문서의 실제 생성일자(파일 내부 메타데이터 기준)를 인덱스 시점에 추출하여 Redis에 저장하고,
KB 전체 reindex 시 해당 날짜 오름차순(오래된 문서 우선)으로 큐에 적재한다.

---

## 기능 요건

### FR-1. 문서 생성일자 추출 및 저장

- 파일 인덱싱 완료 시 Redis 문서 메타데이터에 `doc_created_at` 필드를 저장한다.
- 파일 타입별 추출 우선순위:
  - **PDF**: 파일 내부 Info dict의 `CreationDate` 필드 사용
  - **DOCX**: `core_properties.created` 필드 사용
  - **기타 / 내부 날짜 없음**: S3 `LastModified`(업로드 시각)를 폴백으로 사용
- 날짜는 ISO 8601 UTC 문자열로 저장한다 (예: `2024-03-15T09:00:00+00:00`).
- 날짜 추출 실패(파싱 오류, 필드 부재)는 오류로 처리하지 않고 S3 `LastModified`로 폴백한다.

### FR-2. 문서 목록 API에 `doc_created_at` 노출

- `GET /api/kb/{id}/docs` 응답의 각 문서 항목에 `doc_created_at` 필드를 포함한다.
- 값이 없는 문서(이전 버전에서 인덱스됨)는 `null`로 반환한다.

### FR-3. Qdrant 청크 payload에 `doc_created_at` 포함

- 청크를 Qdrant에 upsert할 때 payload에 `doc_created_at` 필드를 포함한다.
- 값은 FR-1에서 추출한 것과 동일한 ISO 8601 UTC 문자열이다.
- 이를 통해 향후 벡터 검색 시 날짜 범위 필터 조건(`doc_created_at` range filter)을 적용할 수 있다.

### FR-4. Reindex 큐 적재 순서 — 오래된 문서 우선

- `POST /api/kb/{id}/reindex` 실행 시, 큐에 넣기 전 대상 문서를 정렬한다.
- 정렬 기준 우선순위:
  1. Redis에 `doc_created_at`이 저장된 문서: 해당 값 오름차순
  2. Redis에 값이 없는 문서(미인덱스 포함): S3 `LastModified` 오름차순
- 단일 문서 reindex(`POST /api/kb/{id}/docs/reindex`)는 정렬 대상 없으므로 제외.
- Qdrant payload 변경은 재인덱스 시 반영되며, 기존 청크는 재인덱스 전까지 `doc_created_at` 없이 유지된다 (마이그레이션 불필요).

---

## 비기능 요건

- 날짜 추출은 parse op 내에서 수행하며, 파일 다운로드를 추가로 발생시키지 않는다.
- reindex 정렬을 위해 S3 listing을 추가 호출하지 않는다 (`list_kb_objects` 한 번으로 해결).
- 기존에 인덱스된 문서(Redis에 `doc_created_at` 없음)는 마이그레이션 없이 `null` 허용.

---

## 범위 외

- `POST /api/search`에서 `doc_created_at` 날짜 범위 필터를 검색 조건으로 사용하는 기능
- 생성일자 기반 자동 재인덱스 스케줄링
