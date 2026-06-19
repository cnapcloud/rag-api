# Plan: US-11 Postgres 스키마 설계 및 메타데이터 이전

## Context

Redis에 저장된 KB/문서 메타데이터를 Postgres로 이전한다.
dedup 1단계(US-12)에서 필요한 `simhash_bands` 테이블과 `ON DELETE CASCADE`를 이용한
자동 정리가 Redis로는 구현이 어려워 이전을 먼저 진행한다.
이전 후 Redis는 `queue:ingest` 큐 전용으로만 사용한다.

---

## 1. 의존성 및 설정

**`requirements.txt`**
```
psycopg[binary]>=3.1
```

**`settings.yaml`**
```yaml
postgres:
  host: dagster-postgresql
  port: 5432
  dbname: rag_api
  user: dagster
  password: dagster
  pool_size: 5
```

**`src/config/settings.py`** — `PostgresSettings` 서브모델 추가
```python
class PostgresSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    dbname: str = "rag_api"
    user: str = "dagster"
    password: str = "dagster"
    pool_size: int = 5

class Settings(BaseSettings):
    ...
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
```

---

## 2. `migrations/001_initial_schema.sql`

```sql
CREATE TABLE IF NOT EXISTS knowledge_bases (
    kb_id        TEXT PRIMARY KEY,
    description  TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    kb_id            TEXT NOT NULL REFERENCES knowledge_bases(kb_id),
    object_key       TEXT NOT NULL,
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
    title_hash       TEXT,
    content_simhash  BIGINT,
    PRIMARY KEY (kb_id, object_key)
);

CREATE INDEX IF NOT EXISTS idx_documents_etag
    ON documents (kb_id, etag) WHERE etag IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_documents_title_hash
    ON documents (kb_id, title_hash) WHERE title_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS simhash_bands (
    kb_id        TEXT     NOT NULL,
    band_index   SMALLINT NOT NULL,
    band_value   INTEGER  NOT NULL,
    object_key   TEXT     NOT NULL,
    PRIMARY KEY (kb_id, band_index, band_value, object_key),
    FOREIGN KEY (kb_id, object_key)
        REFERENCES documents(kb_id, object_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_simhash_bands
    ON simhash_bands (kb_id, band_index, band_value);
```

---

## 3. `src/infra/postgres.py`

### 커넥션 풀 + 마이그레이션 runner

```python
import psycopg_pool

_pool: psycopg_pool.ConnectionPool | None = None

def get_pool() -> psycopg_pool.ConnectionPool:
    global _pool
    if _pool is None:
        cfg = get_settings().postgres
        conninfo = f"host={cfg.host} port={cfg.port} dbname={cfg.dbname} ..."
        _pool = psycopg_pool.ConnectionPool(conninfo, min_size=1, max_size=cfg.pool_size)
    return _pool

def run_migrations() -> None:
    """migrations/ 디렉토리의 SQL 파일을 버전 순으로 적용."""
    with get_pool().connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        migration_dir = Path(__file__).parents[2] / "migrations"
        for f in sorted(migration_dir.glob("*.sql")):
            if f.stem not in applied:
                conn.execute(f.read_text())
                conn.execute("INSERT INTO schema_migrations(version) VALUES (%s)", [f.stem])
                logger.info("Migration applied: %s", f.stem)
        conn.commit()
```

### KB CRUD 함수

`register_kb`, `get_kb_meta`, `list_kb_ids`, `delete_kb_meta`
— Redis `kb:{kb_id}` Hash / `kbs` Set 대체

### 문서 CRUD 함수

`set_doc_status`, `get_doc_status`, `list_docs`, `list_docs_by_status`
`get_doc_etag`, `set_doc_etag`, `delete_doc_etag`
`delete_doc_meta`, `delete_kb_docs`
— Redis `doc:{kb_id}:{object_key}` Hash / `docs:{kb_id}` Set / `etag:*` 대체

`set_doc_status`는 `INSERT ... ON CONFLICT (kb_id, object_key) DO UPDATE` 패턴 사용.

---

## 4. 호출 지점 교체

| 파일 | 변경 내용 |
|---|---|
| `src/infra/redis.py` | KB/문서/ETag 관련 함수 제거, 큐 관련만 유지 |
| `src/pipeline/ops/meta.py` | `redis_infra` → `postgres_infra` |
| `src/pipeline/ops/validate.py` | `redis_infra.get_doc_etag` → `postgres_infra.get_doc_etag` |
| `src/api/routers/kb.py` | KB CRUD → `postgres_infra` |
| `src/api/routers/docs.py` | 문서 목록/상태 → `postgres_infra` |
| `src/api/app.py` | `redis.RedisError` 핸들러 정리, `psycopg.Error` → 503 핸들러 추가 |
| `src/main.py` | 서비스 시작 시 `postgres_infra.run_migrations()` 호출 |

---

## 5. 테스트

**`tests/conftest.py`** — `mock_postgres` 픽스처 추가

`fakeredis`처럼 in-memory dict 기반 `FakePostgresStore`를 만들고
`postgres_infra` 함수들을 monkeypatch로 교체.

```python
@pytest.fixture
def mock_postgres(monkeypatch):
    store = FakePostgresStore()
    monkeypatch.setattr("infra.postgres.get_doc_status", store.get_doc_status)
    monkeypatch.setattr("infra.postgres.set_doc_status", store.set_doc_status)
    ...
    return store
```

기존 `mock_redis` 픽스처에서 KB/문서 관련 항목 제거, 큐 관련만 유지.

---

## 6. 백필 스크립트

`scripts/migrate_redis_to_postgres.py`
- Redis에서 `kbs` Set → `knowledge_bases` 테이블
- Redis에서 `doc:{kb_id}:*` Hash 전체 → `documents` 테이블
- 서비스 정지 후 1회 실행

---

## 7. `docs/dev/data-schema.md` 업데이트

Redis 섹션을 Postgres 테이블 구조로 교체.

---

## 검증

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v
.venv/bin/ruff check src/
```

- KB/문서 CRUD API (`/api/kb`, `/api/kb/{id}/docs`) 정상 동작
- 인제스트 파이프라인 정상 동작
- Redis 관련 코드가 큐 외에 남아 있지 않음 확인
