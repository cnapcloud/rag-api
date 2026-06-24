# Plan 15 — Multi-source ingest schema initialization (R-01)

Covers: US-15
Requirement: docs/dev/requirement-multi-source-ingest.md — R-01
Status: todo

---

## Overview

Fresh Postgres schema for the multi-source ingest redesign.
Tables are dropped and recreated — no incremental ALTER TABLE migration.
This plan covers DDL, infra/postgres.py CRUD rewrite, and tests.
**The current upload flow and pipeline will break until R-03 + R-04 are complete.**

---

## Step 1 — DDL migration file

Create `migrations/003_multi_source_schema.sql`.

The migration runner (`run_migrations()`) applies files in alphabetical order, skipping already-applied stems. `003_...` runs after `001` and `002` on existing DBs, and as part of the full sequence on fresh installs.

```sql
-- Drop old tables (cascade handles FKs)
DROP TABLE IF EXISTS simhash_bands;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS connectors;

-- connectors must exist before documents (documents.connector_id FK)
CREATE TABLE connectors (
    connector_id      TEXT         PRIMARY KEY,
    kb_id             TEXT         NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    name              TEXT         NOT NULL,
    source_type       TEXT         NOT NULL,   -- web | confluence | github
    config            JSONB        NOT NULL DEFAULT '{}',
    sync_schedule     TEXT,
    schedule_enabled  BOOLEAN      NOT NULL DEFAULT false,
    sync_status       TEXT         NOT NULL DEFAULT 'idle',   -- idle | running
    sync_started_at   TIMESTAMPTZ,
    last_synced_at    TIMESTAMPTZ,
    status            TEXT         NOT NULL DEFAULT 'active', -- active | paused | error
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE documents (
    doc_id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id               TEXT         NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    source              TEXT         NOT NULL,  -- user-visible display name
    source_type         TEXT         NOT NULL,  -- s3 | web | confluence | github
    source_uri          TEXT         NOT NULL,  -- canonical dedup key
    storage_key         TEXT,
    content_version     TEXT,                   -- S3 ETag | HTTP ETag | version# | blob SHA
    connector_id        TEXT         REFERENCES connectors(connector_id) ON DELETE SET NULL,
    status              TEXT         NOT NULL DEFAULT 'pending',
    deleted_at          TIMESTAMPTZ,
    run_id              TEXT         NOT NULL DEFAULT '',
    error               TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    process_started_at  TIMESTAMPTZ,
    process_finished_at TIMESTAMPTZ,
    chunk_count         INTEGER,
    file_size           BIGINT,
    doc_type            TEXT,
    embedding_model     TEXT,
    doc_created_at      TIMESTAMPTZ,
    title_hash          TEXT,
    content_simhash     BIGINT,
    UNIQUE(kb_id, source_uri)
);

CREATE INDEX idx_documents_content_version
    ON documents (kb_id, content_version) WHERE content_version IS NOT NULL;
CREATE INDEX idx_documents_title_hash
    ON documents (kb_id, title_hash) WHERE title_hash IS NOT NULL;
CREATE INDEX idx_documents_connector
    ON documents (connector_id) WHERE connector_id IS NOT NULL;
CREATE INDEX idx_documents_status
    ON documents (kb_id, status);

CREATE TABLE simhash_bands (
    band_id     UUID     PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id      UUID     NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    kb_id       TEXT     NOT NULL,   -- denormalized for LSH lookup without JOIN
    band_index  SMALLINT NOT NULL,
    band_value  INTEGER  NOT NULL,
    UNIQUE(doc_id, band_index, band_value)
);

CREATE INDEX idx_simhash_bands_lsh
    ON simhash_bands (kb_id, band_index, band_value);
```

### Status values (documents.status)

| Value | Meaning |
|---|---|
| `uploading` | API upload in progress (between row create and object storage write) |
| `fetching` | Connector acquiring content |
| `pending` | Queued — event pushed to Redis, waiting for pipeline pickup |
| `running` | Pipeline in progress |
| `indexed` | Complete, chunks in Qdrant |
| `deleting` | Delete in progress |
| `deleted` | Soft-deleted — row retained, Qdrant chunks removed |
| `failed` | Pipeline or delete failed |

---

## Step 2 — infra/postgres.py CRUD rewrite

### Column order constant and row mapper

Define a module-level column list for `SELECT` queries to decouple indices from SQL:

```python
_DOC_COLS = (
    "doc_id", "kb_id", "source", "source_type", "source_uri", "storage_key",
    "content_version", "connector_id", "status", "deleted_at", "run_id", "error",
    "created_at", "updated_at", "process_started_at", "process_finished_at",
    "chunk_count", "file_size", "doc_type", "embedding_model", "doc_created_at",
    "title_hash", "content_simhash",
)
_DOC_SELECT = ", ".join(_DOC_COLS)

def _row_to_doc(row: tuple) -> dict:
    return dict(zip(_DOC_COLS, row))
```

### New CRUD functions

#### create_doc

```python
def create_doc(
    kb_id: str,
    source_uri: str,
    source: str,
    source_type: str,
    *,
    status: str = "pending",
    storage_key: str | None = None,
    content_version: str | None = None,
    connector_id: str | None = None,
    file_size: int | None = None,
    doc_type: str | None = None,
) -> dict:
    # INSERT ... RETURNING _DOC_COLS
    # Raises psycopg.errors.UniqueViolation on duplicate (kb_id, source_uri)
```

#### get_doc_by_id

```python
def get_doc_by_id(doc_id: str) -> dict | None:
    # SELECT _DOC_SELECT FROM documents WHERE doc_id = %s
```

#### get_doc_by_source_uri

```python
def get_doc_by_source_uri(kb_id: str, source_uri: str) -> dict | None:
    # SELECT _DOC_SELECT FROM documents WHERE kb_id = %s AND source_uri = %s
```

#### update_doc_fields

```python
def update_doc_fields(doc_id: str, fields: dict) -> None:
    # UPDATE documents SET updated_at = NOW(), <fields> WHERE doc_id = %s
    # fields keys must be a subset of allowed columns (validated at call site)
    # Always sets updated_at; caller must include process_started_at / process_finished_at
    # if needed.
```

#### soft_delete_doc

```python
def soft_delete_doc(doc_id: str) -> None:
    # UPDATE documents
    # SET status = 'deleted', deleted_at = NOW(), updated_at = NOW()
    # WHERE doc_id = %s
```

#### list_docs

```python
def list_docs(
    kb_id: str,
    *,
    include_deleted: bool = False,
    status_filter: str | None = None,
) -> list[dict]:
    # SELECT _DOC_SELECT FROM documents WHERE kb_id = %s
    #   [AND status != 'deleted'  -- unless include_deleted=True]
    #   [AND status = %s          -- if status_filter is set]
    # ORDER BY created_at DESC
```

#### list_docs_paginated

Update signature and query to add `include_deleted: bool = False` parameter.
Exclude `status='deleted'` rows by default in both the page query and the total count query.

### Deprecated functions to remove

| Function | Replacement |
|---|---|
| `set_doc_status(kb_id, doc_source, fields)` | `update_doc_fields(doc_id, fields)` |
| `get_doc_status(kb_id, doc_source)` | `get_doc_by_id` / `get_doc_by_source_uri` |
| `list_docs_by_status(kb_id, status)` | `list_docs(kb_id, status_filter=status)` |
| `get_doc_etag(kb_id, doc_source)` | field in doc dict from `get_doc_by_id` |
| `set_doc_etag(kb_id, doc_source, etag)` | `update_doc_fields(doc_id, {"content_version": etag})` |
| `delete_doc_etag(kb_id, doc_source)` | removed — content_version nulled via `update_doc_fields` |
| `delete_doc_meta(kb_id, doc_source)` | `soft_delete_doc(doc_id)` |

**Note:** Removing these functions will cause compile-time errors in pipeline ops, docs router, and kb router. Those call sites are intentionally left broken until R-03 (upload flow) and R-04 (pipeline) fix them. Do not add compatibility shims.

---

## Step 3 — Update docs/dev/data-schema.md

Replace the `documents` table schema section with the new field list.
Add `connectors` table section.
Update `simhash_bands` section.
Update the Status field values table (add uploading, fetching, deleted, deleting).
Remove the `etag` index; add `idx_documents_content_version`.

---

## Step 4 — Unit tests

File: `tests/unit/test_postgres_crud.py`

Use `unittest.mock.MagicMock` / `patch` to mock `get_pool()`.
Each test builds a fake `conn` mock that returns preset rows.

Test cases:

| Test | Scenario |
|---|---|
| `test_create_doc_returns_dict` | INSERT returns full row mapped to dict |
| `test_get_doc_by_id_found` | SELECT returns row |
| `test_get_doc_by_id_not_found` | fetchone returns None → function returns None |
| `test_get_doc_by_source_uri_found` | SELECT by UNIQUE key |
| `test_update_doc_fields_sets_updated_at` | SQL includes `updated_at = NOW()` |
| `test_soft_delete_sets_status_and_deleted_at` | status='deleted', deleted_at=NOW() |
| `test_list_docs_excludes_deleted_by_default` | WHERE clause excludes deleted |
| `test_list_docs_include_deleted_flag` | include_deleted=True omits the exclusion |
| `test_list_docs_status_filter` | status_filter='indexed' adds AND status= |

---

## Affected files

| File | Action |
|---|---|
| `migrations/003_multi_source_schema.sql` | create |
| `src/infra/postgres.py` | rewrite CRUD section; keep KB CRUD unchanged |
| `docs/dev/data-schema.md` | update schema reference |
| `tests/unit/test_postgres_crud.py` | create |

---

## Known break points after this step (expected, fixed in later R items)

| File | Broken by |
|---|---|
| `src/api/routers/docs.py` | removed `set_doc_status`, `delete_doc_meta`, `get_doc_status` |
| `src/api/routers/kb.py` | removed `list_docs`, `delete_doc_meta` signatures changed |
| `src/pipeline/ops/validate.py` | removed `get_doc_status(kb_id, doc_source)` |
| `src/pipeline/ops/meta.py` | removed `set_doc_status(kb_id, doc_source, ...)` |
| `src/pipeline/ops/upsert.py` | doc_key-based Qdrant filter no longer has a source field |
