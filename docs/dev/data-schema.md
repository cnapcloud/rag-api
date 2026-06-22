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
    ├── doc_key            : str      — "{kb_id}::{doc_source}" (doc-level delete filter key)
    ├── doc_source         : str      — document source identifier (S3 path, URL, Confluence link, etc.)
    ├── doc_type           : str      — file extension (pdf, docx, txt, md, hwp)
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
                                        (only present for documents indexed after US-10)
```

### Delete filter pattern

```python
# Delete all chunks for a document by doc_key
Filter(must=[FieldCondition(key="doc_key", match=MatchValue(value=doc_key))])
```

---

## 2. Postgres — Document metadata (US-11 onwards)

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

### `documents` table

Replaces Redis `doc:{kb_id}:{doc_source}` hash, `docs:{kb_id}` set, and `etag:{kb_id}:{doc_source}` key.

```
documents
├── kb_id            TEXT NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE
├── doc_source       TEXT NOT NULL
├── status           TEXT NOT NULL DEFAULT 'pending'  -- pending | running | indexed | deleting | failed
├── etag             TEXT                             -- S3 ETag (MD5 hex, quotes stripped)
├── run_id           TEXT NOT NULL DEFAULT ''         -- Dagster run ID or "direct"
├── created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()  -- set on INSERT, never updated
├── updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()  -- updated on every state change
├── chunk_count      INTEGER                          -- chunk count after indexed
├── file_size        BIGINT                           -- file size in bytes
├── doc_type         TEXT                             -- file extension (pdf, docx, …)
├── embedding_model  TEXT                             -- embedding model name
├── error            TEXT                             -- failure message (status=failed)
├── doc_created_at   TIMESTAMPTZ                      -- actual document creation date (US-10)
├── title_hash       TEXT                             -- SHA-256 of doc_source, for dedup (US-12)
├── content_simhash  BIGINT                           -- 64-bit SimHash of body, for dedup (US-12)
└── PRIMARY KEY (kb_id, doc_source)
```

Indexes:
- `idx_documents_etag` on `(kb_id, etag) WHERE etag IS NOT NULL`
- `idx_documents_title_hash` on `(kb_id, title_hash) WHERE title_hash IS NOT NULL`

### `simhash_bands` table (dedup 1단계 준비 — US-12)

```
simhash_bands
├── kb_id        TEXT NOT NULL
├── band_index   SMALLINT NOT NULL    -- 0-3 (64bit → 16bit × 4 bands)
├── band_value   INTEGER NOT NULL
├── doc_source   TEXT NOT NULL
├── PRIMARY KEY (kb_id, band_index, band_value, doc_source)
└── FOREIGN KEY (kb_id, doc_source) REFERENCES documents ON DELETE CASCADE
```

Index: `idx_simhash_bands` on `(kb_id, band_index, band_value)`

### Status field values

| Status | Meaning |
|--------|---------|
| `pending` | Queued — event pushed to Redis, waiting for worker pickup |
| `running` | Pipeline processing in progress |
| `indexed` | Ingest complete, chunks stored in Qdrant |
| `deleting` | Delete in progress |
| `failed` | Ingest or delete failed — see `error` column |

---

## 3. Redis — Queue only (US-11 onwards)

Redis is used exclusively for the ingest and delete event queues.

```
rag:upload:queue   List   -- ingest event queue (lpush/rpop)
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
| Schema migrations | `migrations/001_initial_schema.sql` |
| Redis queue client | `src/infra/redis.py` |
