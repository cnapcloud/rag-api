# Data Schema Reference

## 1. Qdrant — PointStruct (chunk level)

Collection name = `{kb_id}` (one per KB)

```
PointStruct
├── id            : UUID     — new UUID per chunk on every upsert
├── vector
│   ├── dense     : float[]  — Ollama / OpenAI dense embedding
│   └── sparse    : SparseVector { indices: int[], values: float[] }
│                             — BM25 FastEmbed sparse embedding
└── payload
    ├── kb_id              : str      — Knowledge Base ID
    ├── doc_id             : str      — 16-char hex ID of the parent document row (delete filter key)
    ├── title              : str      — user-visible display name (mirrors documents.title)
    ├── source_type        : str      — s3 | web | confluence | github
    ├── source             : str      — canonical dedup key (mirrors documents.source)
    ├── doc_type           : str      — file extension (pdf, docx, txt, md, html, rst, …)
    ├── chunk_index        : int      — chunk sequence number within document (0-based)
    ├── total_chunks       : int      — total chunk count for this document
    ├── page_num           : str|null — original page number (PDF page_label; null if absent)
    ├── text               : str      — chunk body text
    ├── embedding_model    : str      — embedding model name
    ├── embedding_provider : str      — ollama / openai
    ├── chunk_strategy     : str      — recursive / semantic
    ├── chunk_size         : int      — chunk size setting (tokens)
    ├── chunk_overlap      : int      — chunk overlap setting (tokens)
    ├── updated_at         : str      — ISO 8601 UTC, index timestamp
    └── doc_created_at     : str      — ISO 8601 UTC, actual document creation date
```

### Delete filter pattern

```python
# Delete all chunks for a document by doc_id
Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])
```

---

## 2. Postgres — Document metadata

### `knowledge_bases` table

```
knowledge_bases
├── kb_id        TEXT PRIMARY KEY
├── kb_name      TEXT NOT NULL DEFAULT ''
├── tags         TEXT[] NOT NULL DEFAULT '{}'
├── description  TEXT DEFAULT NULL
├── status       TEXT NOT NULL DEFAULT 'active'   -- active | deleting
├── created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
└── updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
```

Indexes:
- `idx_kb_tags` on `tags` using GIN

### `connectors` table

```
connectors
├── connector_id      TEXT         PRIMARY KEY   -- 16-char hex, app-generated (generate_id())
├── kb_id             TEXT         NOT NULL FK knowledge_bases (ON DELETE CASCADE)
├── name              TEXT         NOT NULL
├── source_type       TEXT         NOT NULL   -- web | confluence | github
├── config            JSONB        NOT NULL DEFAULT '{}'
│                                    web:        {seed_urls[], depth, include_patterns, exclude_patterns, max_pages,
│                                                 request_timeout_sec, crawler}
│                                    confluence: {base_url, space_key, auth_token_secret?, exclude_labels[]}
│                                    github:     {owner, repo, ref, paths[], include_extensions[], auth_token_secret?}
├── sync_schedule     TEXT         -- cron expression (NULL = no schedule)
├── schedule_enabled  BOOLEAN      NOT NULL DEFAULT false
├── sync_status       TEXT         NOT NULL DEFAULT 'idle'   -- idle | running
├── sync_started_at   TIMESTAMPTZ
├── last_synced_at    TIMESTAMPTZ
├── status            TEXT         NOT NULL DEFAULT 'active' -- active | paused | error
├── created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
└── updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW()
```

### `documents` table

```
documents
├── doc_id              TEXT         PRIMARY KEY   -- 16-char hex, app-generated (generate_id())
├── kb_id               TEXT         NOT NULL FK knowledge_bases (ON DELETE CASCADE)
├── title               TEXT         NOT NULL   -- user-visible display name
│                                                 s3:         original filename (e.g. report.pdf)
│                                                 web:        page <title> (source used as placeholder before fetch)
│                                                 confluence: page title from API response
│                                                 github:     file path (e.g. docs/guide.md)
├── source_type         TEXT         NOT NULL   -- s3 | web | confluence | github
├── source              TEXT         NOT NULL   -- canonical dedup key
│                                                 s3:         {filename}
│                                                 web:        https://...
│                                                 confluence: confluence://{space}/{page_id}
│                                                 github:     github://{owner}/{repo}/{ref}/{path}
├── storage_key         TEXT                    -- object storage path used by pipeline
├── content_version     TEXT                    -- S3 ETag | HTTP ETag | Confluence version# | blob SHA
├── connector_id        TEXT         FK connectors (ON DELETE SET NULL; NULL = direct upload)
├── status              TEXT         NOT NULL DEFAULT 'pending'
├── deleted_at          TIMESTAMPTZ             -- set when status -> deleted (NULL otherwise)
├── run_id              TEXT         NOT NULL DEFAULT ''
├── error               TEXT
├── created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
├── updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
├── process_started_at  TIMESTAMPTZ             -- set when status -> running
├── process_finished_at TIMESTAMPTZ             -- set when status -> indexed or failed
├── chunk_count         INTEGER
├── file_size           BIGINT
├── doc_type            TEXT                    -- s3: original ext | web: html | confluence: md | github: original ext
├── embedding_model     TEXT
├── doc_created_at      TIMESTAMPTZ             -- actual document creation date (source-specific)
├── title_hash          TEXT
├── content_simhash     BIGINT
├── duplicate_of        TEXT                    -- doc_id of the superseding document (set when status = outdated)
└── UNIQUE(kb_id, source)
```

Indexes:
- `idx_documents_content_version` on `(kb_id, content_version) WHERE content_version IS NOT NULL`
- `idx_documents_title_hash` on `(kb_id, title_hash) WHERE title_hash IS NOT NULL`
- `idx_documents_connector` on `(connector_id) WHERE connector_id IS NOT NULL`
- `idx_documents_status` on `(kb_id, status)`
- `idx_documents_title_trgm` on `title` using GIN (pg_trgm) — 2단계 제목 퍼지 검색용

### `simhash_bands` table

1단계 dedup용 — SimHash 64비트 지문을 16비트 × 4밴드로 분할하여 저장.

```
simhash_bands
├── band_id     TEXT     PRIMARY KEY   -- "{doc_id}:{band_index}" — upsert 안정 키
├── doc_id      TEXT     NOT NULL FK documents(doc_id) ON DELETE CASCADE
├── kb_id       TEXT     NOT NULL   -- denormalized for LSH lookup without JOIN
├── band_index  SMALLINT NOT NULL   -- 0-3 (64-bit -> 16-bit x 4 bands)
├── band_value  INTEGER  NOT NULL   -- 16-bit unsigned band value stored as INTEGER
└── UNIQUE(doc_id, band_index, band_value)
```

Index:
- `idx_simhash_bands_lsh` on `(kb_id, band_index, band_value)` — LSH near-duplicate lookup

### `minhash_bands` table

2단계 dedup용 — MinHash 128개 서명을 개별 행으로 저장 (band_index 0-127).

```
minhash_bands
├── doc_id      TEXT     NOT NULL FK documents(doc_id) ON DELETE CASCADE
├── band_index  SMALLINT NOT NULL   -- 0-127 (128 individual MinHash values)
├── band_hash   BIGINT   NOT NULL   -- MinHash value at this position
└── PRIMARY KEY (doc_id, band_index)
```

Index:
- `idx_minhash_bands_lookup` on `(band_index, band_hash)` — MinHash LSH 후보 조회

LSH candidate query: 16밴드 × 8행 구조로 UNION — 한 밴드의 8개 값이 모두 일치하는 doc_id만 후보로 추출 (`COUNT(*) = 8` 조건).

Extension:
- `pg_trgm` — `documents.title` 컬럼 제목 퍼지 검색용 (`idx_documents_title_trgm` GIN 인덱스)

### Status field values

| Status | Meaning |
|--------|---------|
| `uploading` | API upload in progress (between row create and object storage write) |
| `fetching` | Connector acquiring content from external source |
| `pending` | Queued — event pushed to Redis, waiting for pipeline pickup |
| `running` | Pipeline processing in progress |
| `indexed` | Ingest complete, chunks stored in Qdrant |
| `outdated` | Superseded by a newer version of the same document (dedup verdict); Qdrant chunks may still exist |
| `deleting` | Delete in progress |
| `deleted` | Soft-deleted — row retained, Qdrant chunks removed |
| `failed` | Ingest or delete failed — see `error` column |

---

## 3. Redis — Queue only

Redis is used exclusively for the ingest and delete event queues.

```
rag:upload:queue   List   -- ingest event queue; payload: {doc_id, force} (lpush/rpop)
rag:delete:queue   List   -- delete event queue (lpush/rpop)
```

---

## 4. Source code locations

| Item | File |
|------|------|
| Qdrant payload assembly | `src/pipeline/ops/upsert.py` |
| doc_created_at extraction | `src/pipeline/ops/parse.py` — `_extract_doc_created_at()` |
| Postgres KB/doc CRUD | `src/infra/postgres.py` |
| Document state transitions | `src/pipeline/ops/meta.py` |
| Schema DDL | `migrations/001_initial_schema.sql` |
| Redis queue client | `src/infra/redis.py` |
