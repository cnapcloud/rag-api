# US-11 — Postgres 스키마 설계 및 메타데이터 이전

## 개요

현재 Redis에 저장된 KB/문서 메타데이터를 Postgres로 이전하고, dedup 1단계(US-12)에
필요한 simhash 관련 스키마까지 함께 설계·적용한다.

이전 완료 후 Redis는 `queue:ingest` 큐 전용으로만 사용한다.

---

## 1단계 — 스키마 설계 및 적용

### 대상 테이블

```sql
-- KB 메타데이터
CREATE TABLE knowledge_bases (
    kb_id        TEXT PRIMARY KEY,
    kb_name      TEXT NOT NULL DEFAULT '',
    tags         TEXT[] NOT NULL DEFAULT '{}',
    description  TEXT DEFAULT NULL,
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 문서 메타데이터 (Redis doc:{kb_id}:{doc_source} 대체)
CREATE TABLE documents (
    kb_id            TEXT NOT NULL REFERENCES knowledge_bases(kb_id),
    doc_source       TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'running',
    etag             TEXT,
    run_id           TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    chunk_count      INTEGER,
    file_size        BIGINT,
    doc_type         TEXT,
    embedding_model  TEXT,
    error            TEXT,
    doc_created_at   TIMESTAMPTZ,
    title_hash       TEXT,    -- SHA-256 of doc_source (filename), dedup 1단계용
    content_simhash  BIGINT,  -- 64-bit SimHash of body, dedup 1단계용
    PRIMARY KEY (kb_id, doc_source)
);

-- 역방향 ETag 조회 (다른 파일명, 동일 내용 탐지용)
CREATE INDEX idx_documents_etag ON documents (kb_id, etag) WHERE etag IS NOT NULL;
-- title_hash 빠른 비교
CREATE INDEX idx_documents_title_hash ON documents (kb_id, title_hash) WHERE title_hash IS NOT NULL;

-- SimHash band index (dedup 1단계용)
-- ON DELETE CASCADE: documents 행 삭제 시 band 항목 자동 정리
CREATE TABLE simhash_bands (
    kb_id        TEXT     NOT NULL,
    band_index   SMALLINT NOT NULL,  -- 0~3 (64bit → 16bit × 4조각)
    band_value   INTEGER  NOT NULL,
    doc_source   TEXT     NOT NULL,
    PRIMARY KEY (kb_id, band_index, band_value, doc_source),
    FOREIGN KEY (kb_id, doc_source)
        REFERENCES documents(kb_id, doc_source) ON DELETE CASCADE
);

CREATE INDEX idx_simhash_bands ON simhash_bands (kb_id, band_index, band_value);
```

### 작업 항목

- [ ] `dagster-postgresql` 인스턴스에 `rag_api` 데이터베이스 생성
- [ ] `settings.yaml` + `config/settings.py`에 `postgres` 연결 설정 추가 (host, port, db, user, password, pool_size)
- [ ] `requirements.txt`에 `psycopg[binary]` 추가
- [ ] `migrations/` 디렉토리 생성, `001_initial_schema.sql` 작성 (위 DDL)
- [ ] `src/infra/postgres.py` 작성 — 커넥션 풀 싱글턴
- [ ] 마이그레이션 버전 관리 구현
  - `schema_migrations(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ)` 테이블로 적용 이력 추적
  - 서비스 시작 시 `migrations/` 파일을 버전 순으로 스캔, 미적용 파일만 순서대로 실행
  - 적용 완료 후 `schema_migrations`에 버전 기록

---

## 2단계 — 메타데이터 이전 (Redis → Postgres)

### 교체 대상

| 현재 Redis 키 | 이전 후 |
|---|---|
| `kb:{kb_id}` Hash | `knowledge_bases` 테이블 |
| `kbs` Set | `SELECT kb_id FROM knowledge_bases` |
| `doc:{kb_id}:{doc_source}` Hash | `documents` 테이블 |
| `docs:{kb_id}` Set | `SELECT doc_source FROM documents WHERE kb_id = ?` |
| `etag:{kb_id}:{doc_source}` String | `documents.etag` 컬럼 + 인덱스 |

**Redis에 남기는 것:** `queue:ingest` 큐만

### 작업 항목

- [ ] `src/infra/postgres.py`에 KB CRUD 함수 구현
  - `register_kb`, `list_kb_ids`, `delete_kb_meta`, `get_kb_meta`
- [ ] `src/infra/postgres.py`에 문서 CRUD 함수 구현
  - `set_doc_status`, `get_doc_status`, `list_docs`, `list_docs_by_status`
  - `set_doc_etag`, `get_doc_etag`, `delete_doc_etag`
  - `delete_doc_meta`, `delete_kb_docs`
- [ ] `src/infra/redis.py`에서 KB/문서 관련 함수 제거, 큐 관련만 유지
- [ ] `src/pipeline/ops/meta.py` — postgres infra 호출로 교체
- [ ] `src/pipeline/ops/validate.py` — ETag 조회를 postgres로 교체
- [ ] `src/api/routers/kb.py`, `docs.py` — postgres infra 호출로 교체
- [ ] `src/api/app.py` — 헬스체크 `redis.RedisError` 핸들러 정리, Postgres 핸들러 추가
- [ ] `tests/conftest.py` — `mock_redis` 픽스처를 mock postgres로 교체
- [ ] 운영 데이터 백필 스크립트 작성 (`scripts/migrate_redis_to_postgres.py`)
- [ ] `docs/internal/design/data-schema.md` 업데이트

---

## 완료 기준

- 전체 테스트 통과 (mock postgres 픽스처 기반)
- KB/문서 CRUD API 정상 동작 (Redis 없이)
- 인제스트 파이프라인 정상 동작 (Postgres 기반 상태 관리)
- Redis는 `queue:ingest` 관련 코드만 남음
- `documents` 테이블에 `title_hash`, `content_simhash`, `simhash_bands` 테이블 존재 (dedup 1단계 준비 완료)

---

