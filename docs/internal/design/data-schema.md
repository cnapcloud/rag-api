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
    ├── content_type       : str      — text (default) | ocr_text | image_caption | table — how
    │                                   this chunk's text was produced (rag-ent-api image_ocr /
    │                                   table_layout plugins)
    ├── chunk_index        : int      — chunk sequence number within document (0-based)
    ├── total_chunks       : int      — total chunk count for this document
    ├── page_num           : int|null — physical page number within the document (1-based; null if not paginated)
    ├── page_label         : str|null — PDF page label (/PageLabels, e.g. "i", "A-1"; null if the PDF defines none)
    ├── text               : str      — chunk body text
    ├── embedding_model    : str      — embedding model name
    ├── embedding_provider : str      — ollama / openai
    ├── chunk_strategy     : str      — recursive / semantic / hierarchical
    ├── chunk_size         : int|int[] — chunk size setting (tokens); list of levels for
    │                                    hierarchical (largest -> smallest, last = leaf size)
    ├── chunk_overlap      : int      — chunk overlap setting (tokens)
    ├── updated_at         : str      — ISO 8601 UTC, index timestamp
    ├── doc_created_at     : str      — ISO 8601 UTC, actual document creation date
    └── parent_chunk_id    : str|null — PK of this chunk's immediate ancestor in `parent_chunks`
                                        (below); null when chunking.strategy != "hierarchical"
                                        or for pre-existing chunks (design:
                                        parent-child-chunking.md §4.2)
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

### `kb_settings_overrides` table

KB별로 `settings.yaml`의 `ingestion`/`chunking`/`dedup` 값을 오버라이드. 자세한 설계는
[kb-settings-override.md](kb-settings-override.md) 참고 — 행 하나 = 오버라이드 키 하나(JSONB
블롭이 아닌 이유는 §10 참고, PATCH의 lost update 회피).

```
kb_settings_overrides
├── kb_id       TEXT        NOT NULL FK knowledge_bases (ON DELETE CASCADE)
├── key         TEXT        NOT NULL   -- dot-notation, Settings 필드 경로 (예: "ingestion.max_file_size_mb")
├── value       JSONB       NOT NULL   -- 스칼라/객체 어떤 JSON 값이든
├── updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
└── PRIMARY KEY (kb_id, key)
```

`key`는 애플리케이션 레벨에서 두 단계로 검증됨(DB 제약 아님, [kb-settings-override.md §9.1](kb-settings-override.md#91-검증--allow-list가-먼저다)):
1. `ingestion.`/`chunking.`/`dedup.` 접두사만 허용(allow-list) — `provider`/`redis`/`postgres`
   등 인프라 자격증명 섹션은 애초에 저장 불가.
2. 접두사를 통과해도 특정 leaf 키(`ingestion.parser_plugins`, `dedup.simhash.ngram`/`num_bands`/
   `simhash_bits`, `dedup.minhash.user_words_path`)는 deny-list로 거부.

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
├── last_error        TEXT                                  -- last sync failure message (cleared on manual status change)
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
├── last_error          TEXT
├── created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
├── updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW()
├── process_started_at  TIMESTAMPTZ             -- set when status -> running
├── process_finished_at TIMESTAMPTZ             -- set when status -> indexed or failed
├── chunk_count         INTEGER
├── file_size           BIGINT
├── doc_type            TEXT                    -- s3: original ext | web: html | confluence: md | github: original ext
├── embedding_model     TEXT
├── chunk_strategy      TEXT                    -- recursive | semantic | hierarchical (resolved KB
│                                                 chunking.strategy at ingest time, set on set_indexed)
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

### `parent_chunks` table

`chunking.strategy = "hierarchical"`로 인덱싱된 문서의 상위(ancestor) 청크 계층 — 자기참조
트리. leaf(실제 검색 대상) 청크는 Qdrant에만 있고, 이 테이블에는 leaf 바로 위 레벨부터
root까지만 저장된다. 전체 설계는 [parent-child-chunking.md §4.1](parent-child-chunking.md#41-postgres--parent_chunks-테이블-신규-자기참조-트리) 참고.

```
parent_chunks
├── chunk_id     TEXT         PRIMARY KEY   -- "{doc_id}:{idx}", idx는 문서 전체 전역 카운터
│                                              (simhash_bands.band_id와 동일한 합성 키 패턴)
├── doc_id       TEXT         NOT NULL FK documents(doc_id) ON DELETE CASCADE
├── kb_id        TEXT         NOT NULL FK knowledge_bases(kb_id) ON DELETE CASCADE
├── level        SMALLINT     NOT NULL   -- 0 = root ... leaf 바로 위 레벨까지 (조회/디버깅용)
├── parent_id    TEXT         FK parent_chunks(chunk_id) ON DELETE CASCADE  -- NULL = root
├── chunk_index  INTEGER      NOT NULL   -- 같은 level 내 시퀀스 번호 (0-based)
├── text         TEXT         NOT NULL   -- 이 노드 전체 텍스트
├── child_count  INTEGER      NOT NULL   -- 바로 아래 레벨의 실제 자식 수 (min_chunk_chars 필터
│                                           통과분만; 0인 행은 저장하지 않음)
├── page_num     INTEGER                 -- 소속 페이지 번호, 비페이지네이션 문서는 NULL
├── page_label   TEXT                    -- 소속 페이지 라벨, 없으면 NULL
└── created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
```

Indexes:
- `idx_parent_chunks_doc` on `(doc_id)`
- `idx_parent_chunks_parent` on `(parent_id)` — cascade delete 및 상위 조회용

삭제: soft/hard delete 양쪽 모두 `purge_doc_artifacts()`에서 `delete_parent_chunks_by_doc()`을
호출해 정리(dedup bands와 동일 패턴). hard delete는 `documents` 삭제 시 `ON DELETE CASCADE`로도
자동 정리됨.

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
| `failed` | Ingest or delete failed — see `last_error` column |

---

## 3. Redis — Queue only

Redis is used exclusively for the ingest and delete event queues.

```
rag:upload:queue   List        -- ingest event queue; payload: {doc_id, force} (lpush/rpop)
rag:delete:queue   List        -- delete event queue (lpush/rpop)
rag:upload:delay   Sorted Set  -- ingest retry queue; member=payload JSON, score=ready_at (unix ts)
rag:delete:delay   Sorted Set  -- delete retry queue; member=payload JSON, score=ready_at (unix ts)
```

A doc blocked by an active `running`/`deleting` state is pushed to the matching delay queue
instead of being processed immediately. Delay/dedup mechanics are covered in
[duplicate-request-handling.md](duplicate-request-handling.md).

---

## 4. Source code locations

| Item | File |
|------|------|
| Qdrant payload assembly | `src/pipeline/steps/upsert.py` |
| doc_created_at extraction | `src/pipeline/steps/parse.py` — `_extract_doc_created_at()` |
| Postgres KB/doc CRUD | `src/infra/postgres.py` |
| Document state transitions | `src/pipeline/steps/meta.py` |
| Schema DDL | `migrations/001_initial_schema.sql`, `migrations/002_kb_settings_overrides.sql`, `migrations/003_parent_chunks.sql` |
| Redis queue client | `src/infra/redis.py` |
| KB 설정 오버라이드 리졸버 | `src/config/settings.py` — `resolve_settings(kb_id)` |
| `parent_chunks` CRUD | `src/rag_api/infra/postgres.py` — `save_parent_chunks`, `get_parent_chunks`, `delete_parent_chunks_by_doc` |
| Auto-merge 병합 로직 | `src/rag_api/query/retriever.py` — `_auto_merge_parents` |
