# Multi-Source Ingest: Flow & Schema Redesign Requirements

## 1. Current Flow Problems

```
POST /upload -> object storage upload -> (object storage webhook) -> enqueue_upload_event() -> set_pending() -> documents row created
```

Three problems:

1. documents row is created by the Webhook — if Webhook is delayed or fails, no row exists
2. `source` doubles as object storage path and document unique ID — cannot be applied to external sources (URLs, etc.)
3. Pipeline queue event carries `{kb_id, source, etag}` — assumes object storage, no source flexibility

---

## 2. Redesigned Flows

### Flow A — File Upload (API)

```
POST /api/kb/{kb_id}/docs/upload
  [1] Verify KB exists, validate file extension
  [2] Lookup documents by (kb_id, source_uri)
      |- not found               -> proceed as new document
      |- status=uploading        -> 409 (upload already in progress)
      |- status=running          -> 409 (pipeline already in progress)
      |- status=fetching         -> 409 (connector acquisition in progress)
      |- status=deleting         -> 409 (delete in progress)
      |- status=deleted          -> proceed as re-upload (keep existing doc_id, clear deleted_at)
      `- indexed/pending/failed  -> proceed as re-upload (keep existing doc_id)
  [3] UPSERT documents row
      |- new:      INSERT  doc_id=NEW UUID, status=uploading, source_type=s3
      `- existing: UPDATE  status=uploading  (doc_id unchanged)
  [4] object storage upload
        failure -> documents status=failed, return error
  [5] Compare content_version  (storage ETag vs current content_version)
      |- prior status was deleted -> skip comparison, always proceed (Qdrant chunks are gone)
      |- same                     -> restore status=indexed, skip pipeline
      |                              200 response  {doc_id, source, status: "unchanged"}
      `- changed                  -> proceed
  [6] Update documents
        status=pending, content_version=storage_etag, file_size, storage_key
  [7] Push to Redis queue  {doc_id, force=false}
  [8] 202 response  {doc_id, source}
```

Key decisions:
- doc_id is reused on re-upload (not reassigned) — Qdrant chunks are deleted and re-inserted under the same doc_id
- ETag comparison happens after object storage upload (ETag is returned by the storage backend); uploading unchanged content is accepted as a trade-off over pre-computing MD5 in memory
- Concurrent operation guard (409) prevents race conditions on the same document

object storage webhook (/internal/s3-event) is removed entirely.
All ingest entry points are the upload API or a Connector.
Direct object storage uploads (bypassing the API) are not a supported path —
the pipeline cannot run without a documents row, which only the API or Connector creates.

### Flow B — External Source Connector (new)

```
Trigger: POST /api/connectors/{connector_id}/sync  OR  Dagster Schedule
  [1] Load connector config (kb_id, source_type, config)
  [2] Fetch document list from source
        web:        crawl seed_urls
        confluence: list pages via space API
        github:     list files via path API
  [3] For each document:
      [3-1] Lookup documents by (kb_id, source_uri)
            not found       -> create row (status=fetching)
            status=deleted  -> set status=fetching, skip content_version comparison (chunks are gone)
            found (other)   -> compare content_version
                                 unchanged -> skip
                                 changed   -> set status=fetching
      [3-2] Fetch content (HTTP GET / Confluence API / GitHub API)
              failure -> status=failed, continue to next document
              web: extract <title> from HTML -> update source field
                   no <title> -> source remains as source_uri (fallback)
      [3-3] Stage to object storage  key = {kb_id}/{source_type}/{doc_id}.{ext}
              failure -> status=failed, continue to next document
      [3-4] Update documents
              status=pending, storage_key, content_version, file_size
      [3-5] Push to Redis queue  {doc_id, force=false}
  [4] Update connector.last_synced_at
```

### Flow C — Pipeline (common, source-agnostic)

```
Redis Queue: {doc_id, force}
  |
[validate_op]
  Lookup documents by doc_id
    -> retrieve storage_key, content_version, file_size
    -> set status=running, process_started_at=NOW()
    -> force=false: skip if content_version matches already-indexed version
    -> file_size exceeds limit -> failed
  |
[parse_op]
  Download file from object storage using storage_key
  -> produce Document[] (file-based, source-agnostic)
  |
[chunk_op] -> [embed_op]
  |
[upsert_op]
  Delete existing chunks filter: doc_id  (currently: doc_key)
  Upsert new chunks (Qdrant payload includes doc_id)
  |
[meta_op]
  Update: status=indexed, chunk_count, embedding_model, process_finished_at=NOW()
```

### Status Transitions

```
[API upload]
  (none) -> uploading -> pending -> running -> indexed
                      \-> failed

[Connector]
  (none) -> fetching -> pending -> running -> indexed
                     \-> failed

[Delete]
  indexed -> deleting -> deleted  (row retained)
           \-> failed

  Delete execution order (within deleting state):
    [1] Delete Qdrant chunks by doc_id  <- first, so search stops returning results immediately
    [2] Delete object storage file
    [3] Set status=deleted, deleted_at=NOW()
```

---

## 3. Table Redesign

### documents — major changes

| Change | Detail |
|---|---|
| PK change | composite `(kb_id, source)` -> `doc_id UUID PRIMARY KEY` |
| Unique constraint added | `UNIQUE(kb_id, source_uri)` — dedup key per source |
| Fields added | `doc_id`, `source_type`, `source_uri`, `storage_key`, `content_version`, `connector_id` |
| Status added | `uploading` (API upload in progress), `fetching` (connector acquiring content) |
| etag removed | replaced by `content_version TEXT` (fresh schema — not migrated) |

Full field definition:

```
documents
|- doc_id           UUID         PRIMARY KEY
|- kb_id            TEXT         FK knowledge_bases (ON DELETE CASCADE)
|- source           TEXT         user-visible display name (always human-readable; never a raw URL)
|                                  s3:         original filename (e.g. report.pdf)
|                                  web:        page <title> — set after fetch; source_uri used as placeholder before fetch
|                                  confluence: page title from API response — set at row creation
|                                  github:     file path (e.g. docs/guide.md) — set at row creation
|- source_type      TEXT         s3 | web | confluence | github
|- source_uri       TEXT         canonical unique URI (dedup key)
|                                  s3:         {filename}  (kb_id already scoped by UNIQUE constraint)
|                                  web:        https://...
|                                  confluence: confluence://{space}/{page_id}
|                                  github:     github://{owner}/{repo}/{ref}/{path}
|- storage_key      TEXT         object storage path for pipeline to fetch the file
|                                  (S3 key, GCS object name, etc. — implementation-specific)
|                                  file is stored with object metadata (see storage_key metadata below)
|- content_version  TEXT         storage ETag | HTTP ETag | Confluence version# | blob SHA
|- connector_id     TEXT         FK connectors (NULL = direct upload)
|- status           TEXT         uploading | fetching | pending | running | indexed | deleting | deleted | failed
|- deleted_at       TIMESTAMPTZ  -- set when status -> deleted (NULL otherwise)
|- run_id               TEXT
|- error                TEXT
|- created_at           TIMESTAMPTZ
|- updated_at           TIMESTAMPTZ
|- process_started_at   TIMESTAMPTZ  -- set when status -> running (pipeline pickup)
|- process_finished_at  TIMESTAMPTZ  -- set when status -> indexed or failed
|- chunk_count      INTEGER
|- file_size        BIGINT
|- doc_type         TEXT         file format stored in object storage
|                                  s3:         original file extension (pdf, docx, md, …)
|                                  web:        html
|                                  confluence: md  (converted to markdown before staging)
|                                  github:     original file extension (md, txt, rst, …)
|- embedding_model  TEXT
|- doc_created_at   TIMESTAMPTZ  actual document creation date (source-specific)
|                                  s3:         extracted from file metadata (e.g. PDF CreationDate)
|                                  web:        HTML <meta> date or HTTP Last-Modified header
|                                  confluence: page created_at from Confluence API
|                                  github:     date of first commit touching the file
|- title_hash       TEXT
`- content_simhash  BIGINT

UNIQUE(kb_id, source_uri)
```

#### soft delete query behavior

`status=deleted` rows are excluded from all default list/query operations.
Callers must opt in explicitly to see deleted documents.

| Query | Behavior |
|---|---|
| `GET /api/kb/{kb_id}/docs` | excludes `status=deleted` (default) |
| `GET /api/kb/{kb_id}/docs?status=deleted` | returns deleted documents only |
| `GET /api/kb/{kb_id}/docs?status=indexed` | returns indexed documents only |
| `GET /api/kb/{kb_id}/docs?include_deleted=true` | returns all documents including deleted |

This applies equally to `GET /api/connectors/{connector_id}/docs` and any internal query that lists documents.
Search (`POST /api/search`) always excludes `status=deleted` with no override option.

#### storage_key object metadata

When staging a file to object storage, the following user-defined metadata is attached to the object.
This makes objects self-describing and enables recovery without querying Postgres.

S3-compatible metadata headers (prefix `x-amz-meta-` in AWS/MinIO, `x-goog-meta-` in GCS):

| Metadata key | Value | Example |
|---|---|---|
| `doc-id` | doc_id UUID | `a1b2c3d4-...` |
| `kb-id` | knowledge base ID | `kb-01` |
| `source-type` | source type | `web` |
| `source` | user-visible label (original filename or page title) | `report.pdf` |
| `source-uri` | canonical URI | `https://example.com/docs/guide` |

These values are written at upload time by the API or Connector.
The pipeline does not rely on these values — it always reads from the documents table.

#### source_uri normalization rules

`source_uri` is the dedup key. The same page must produce the same URI regardless of how it is referenced.
Normalization is applied by the caller (upload API or connector) before INSERT/lookup.

| Rule | Before | After |
|---|---|---|
| Force https | `http://example.com/page` | `https://example.com/page` |
| Lowercase host | `https://Example.COM/page` | `https://example.com/page` |
| Remove trailing slash | `https://example.com/docs/` | `https://example.com/docs` |
| Remove fragment | `https://example.com/page#section` | `https://example.com/page` |
| Remove tracking params | `?utm_source=x&utm_medium=y` | removed |
| Sort remaining query params | `?b=2&a=1` | `?a=1&b=2` |

For non-web source types, normalization rules are source-specific:

| source_type | source_uri format | normalization |
|---|---|---|
| s3 | `{filename}` | none (controlled by API) |
| confluence | `confluence://{space}/{page_id}` | lowercase space key |
| github | `github://{owner}/{repo}/{ref}/{path}` | lowercase owner/repo |

### connectors — new table

```
connectors
|- connector_id    TEXT         PRIMARY KEY
|- kb_id           TEXT         FK knowledge_bases (ON DELETE CASCADE)  -- target KB (required)
|- name            TEXT         user-visible label
|- source_type     TEXT         web | confluence | github
|- config          JSONB        source-specific settings
|                                 web:        {seed_urls[], depth, include_pattern}
|                                 confluence: {base_url, space_key, auth_token_secret?}  -- auth_token_secret optional (public sites)
|                                 github:     {owner, repo, ref, paths[], auth_token_secret?}  -- auth_token_secret optional (public repos)
|- sync_schedule    TEXT         cron expression (NULL = no schedule defined)
|- schedule_enabled BOOLEAN      DEFAULT false -- true = Dagster Schedule fires automatically
|                                              -- false = cron expression is kept but does not fire
|                                              -- manual sync via API always works regardless
|- sync_status      TEXT         idle | running               -- current sync run state
|- sync_started_at  TIMESTAMPTZ                              -- set when sync begins, cleared on finish
|- last_synced_at   TIMESTAMPTZ                              -- set on successful completion
|- status           TEXT         active | paused | error      -- connector lifecycle state
|- created_at       TIMESTAMPTZ
`- updated_at       TIMESTAMPTZ
```

### simhash_bands — redesigned schema

```
-- current
PRIMARY KEY (kb_id, source, band_index, band_value)
FOREIGN KEY (kb_id, source) REFERENCES documents

-- new
simhash_bands
|- band_id     UUID         PRIMARY KEY
|- doc_id      UUID         FK documents(doc_id) ON DELETE CASCADE
|- kb_id       TEXT         FK knowledge_bases  -- denormalized for LSH lookup without JOIN
|- band_index  SMALLINT     NOT NULL   -- 0-3 (64-bit -> 16-bit x 4 bands)
|- band_value  INTEGER      NOT NULL

UNIQUE(doc_id, band_index, band_value)
INDEX(kb_id, band_index, band_value)  -- LSH lookup: find near-duplicates within same KB
```

### Qdrant chunk payload — changes

```
add:    doc_id  str   -- UUID, used as delete filter key
remove: doc_key       -- {kb_id}::{source} pattern deprecated
```

---

## 4. Connector API Requirements

### 4-1. Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/connectors` | Create connector |
| GET | `/api/connectors` | List connectors (filterable by kb_id, source_type, status) |
| GET | `/api/connectors/{connector_id}` | Get connector detail |
| PATCH | `/api/connectors/{connector_id}` | Update config / schedule / status |
| DELETE | `/api/connectors/{connector_id}` | Delete connector and all associated documents (async) |
| POST | `/api/connectors/{connector_id}/sync` | Trigger manual sync |
| GET | `/api/connectors/{connector_id}/sync/status` | Get current sync status |
| GET | `/api/connectors/{connector_id}/docs` | List documents ingested by this connector |

### 4-2. POST /api/connectors — request body

```json
{
  "kb_id": "kb-01",
  "name": "Product Docs",
  "source_type": "web",
  "config": { ... },
  "sync_schedule": "0 2 * * *",
  "schedule_enabled": true
}
```

`config` schema per source_type:

```json
// web
{
  "seed_urls": ["https://example.com/docs"],
  "depth": 2,
  "include_patterns": ["https://example.com/docs/*"],
  "exclude_patterns": [],
  "max_pages": 200,
  "request_timeout_sec": 30,
  "crawler": "trafilatura"
}

// confluence
{
  "base_url": "https://company.atlassian.net",
  "space_key": "DEV",
  "auth_token_secret": "secret-key-name",  // optional — omit for public Confluence sites
  "exclude_labels": ["draft", "archived"]
}

// github
{
  "owner": "myorg",
  "repo": "docs",
  "ref": "main",
  "paths": ["docs/", "README.md"],
  "include_extensions": [".md", ".txt", ".rst"],
  "auth_token_secret": "secret-key-name"   // optional — omit for public repos; unauthenticated rate limit: 60 req/hr
}
```

### 4-3. POST /api/connectors/{connector_id}/sync — execution flow

```
[1] Load connector row from Postgres
      status=paused          -> 409 "connector is paused"
      sync_status=running
        AND sync_started_at > NOW() - stale_timeout (default 30min)
                             -> 409 "sync already in progress"
        AND sync_started_at <= NOW() - stale_timeout
                             -> stale lock detected, proceed (previous run crashed)
[2] Set sync_status=running, sync_started_at=NOW()
[3] Return 202 immediately, continue as BackgroundTask
[4] Dispatch to connector implementation by source_type
      web        -> WebConnector(config).sync(kb_id, connector_id)
      confluence -> ConfluenceConnector(config).sync(kb_id, connector_id)
      github     -> GitHubConnector(config).sync(kb_id, connector_id)
[5] Connector runs Flow B (fetch -> stage -> enqueue) per document
[6] On completion: sync_status=idle, last_synced_at=NOW(), sync_started_at=NULL
    On failure:    sync_status=idle, connector.status=error, error message logged
```

Manual trigger (`POST /sync`) is always allowed regardless of `sync_schedule`.
`sync_schedule` is only an automatic execution setting, not a lock.
Dagster Schedule and manual trigger share the same execution path.

### 4-4. GET /api/connectors/{connector_id}/sync/status — response

```json
{
  "connector_id": "...",
  "status": "active",
  "sync_status": "running",
  "sync_started_at": "2025-01-01T02:00:05Z",
  "last_synced_at": "2024-12-31T02:00:00Z",
  "doc_counts": {
    "indexed": 142,
    "pending": 3,
    "failed": 1,
    "deleted": 5,
    "total": 151
  }
  // total includes all statuses including deleted — full audit view of connector-owned documents
}
```

`doc_counts` is derived from `documents WHERE connector_id = ?` grouped by status.
`sync_status=running` with a stale `sync_started_at` (older than stale_timeout) indicates a crashed sync — the next manual trigger will reset it.

### 4-5. Scheduled sync (Dagster)

A Dagster Schedule fires automatically only when both `sync_schedule` is set AND `schedule_enabled=true`.
At startup, connectors with `sync_schedule != NULL AND schedule_enabled=true` are registered as Dagster Schedules dynamically.
Toggling `schedule_enabled` via PATCH takes effect without a Dagster workspace reload.
Changing `sync_schedule` itself requires a Dagster workspace reload to take effect.
Manual sync via `POST /sync` always works regardless of `schedule_enabled`.

### 4-6. DELETE /api/connectors/{connector_id} — document cascade

Deleting a connector triggers deletion of all associated documents (WHERE connector_id = ?).

```
[1] Set connector.status = deleting
[2] For each document WHERE connector_id = ? AND status != deleted:
      run standard delete flow:
        [a] Delete Qdrant chunks by doc_id
        [b] Delete object storage file
        [c] Set document status = deleted, deleted_at = NOW()
[3] Delete connector row
```

Runs as a BackgroundTask — the API returns 202 immediately.
Documents ingested via this connector but later re-uploaded via API (connector_id = NULL) are not affected.

### 4-7. auth_token_secret handling

`config.auth_token_secret` stores a **key name**, not the token value itself.
The actual token is resolved at runtime from an environment variable or secret store.
`auth_token_secret` is optional — omit for public Confluence sites or public GitHub repos.

```python
token = os.environ[config["auth_token_secret"]] if config.get("auth_token_secret") else None
```

Tokens are never stored in the database.
When `token` is `None`, the connector makes unauthenticated requests (GitHub: 60 req/hr rate limit applies).

### 4-8. DELETE /api/kb/{kb_id} — full cascade

KB 삭제는 연결된 모든 데이터를 제거해야 한다.
Postgres CASCADE로 처리되지 않는 Qdrant 청크와 object storage 파일은 애플리케이션에서 처리한다.

```
[1] For each document WHERE kb_id = ?:
      [a] Delete Qdrant chunks by doc_id
      [b] Delete object storage file by storage_key
[2] DELETE FROM knowledge_bases WHERE kb_id = ?
      -> CASCADE: documents (all rows)
          -> CASCADE: simhash_bands (all rows)
      -> CASCADE: connectors (all rows)
```

Runs as a BackgroundTask — the API returns 202 immediately.
Cascade delete order ensures Qdrant and object storage are cleaned before Postgres rows are removed.

---

## 5. Changed Areas Summary

| Area | Change |
|---|---|
| Postgres DDL | documents, connectors, simhash_bands tables defined from scratch (DROP and recreate — no migration SQL) |
| `api/routers/docs.py` | upload_doc(): row-first order (create row -> object storage -> enqueue) |
| `api/routers/connectors.py` | new — connector CRUD + sync trigger endpoint |
| `infra/postgres.py` | doc_id-based CRUD, connectors CRUD |
| `pipeline/enqueue.py` | queue event structure changed to `{doc_id, force}` |
| `pipeline/ops/validate.py` | lookup documents by doc_id, retrieve storage_key |
| `pipeline/ops/upsert.py` | Qdrant delete filter: `doc_key` -> `doc_id` |
| `pipeline/ops/meta.py` | status updates by doc_id |
| Webhook handler | removed entirely (`/internal/s3-event` endpoint deleted — object storage webhook no longer used) |
| Qdrant payload | add `doc_id` field, remove `doc_key` |
| `connectors/` (new) | WebConnector, ConfluenceConnector, GitHubConnector |
| Dagster | add connector sync Schedule/Job |

---

## 6. Dev Requirements (backlog units)

Tables are initialized fresh (DROP and recreate) — no incremental ALTER TABLE migrations needed.
Each item is independently codeable. R-03 and R-04 must be deployed together (new queue event producer and consumer must go live simultaneously).

| ID | Title | Depends on |
|---|---|---|
| R-01 | Postgres schema: create documents (doc_id UUID PK, UNIQUE(kb_id, source_uri), all fields, full status set, soft delete), connectors, simhash_bands tables — DDL + infra/postgres.py base CRUD | — |
| R-02 | source_uri normalization: pure-function utility + unit tests | R-01 |
| R-03 | File upload flow: row-first (INSERT/UPSERT documents row -> object storage upload with metadata -> enqueue {doc_id, force=false}) | R-01, R-02 |
| R-04 | Pipeline: consume {doc_id, force} from queue; validate / upsert / meta convert to doc_id-based; Qdrant chunk payload add doc_id / remove doc_key | R-01 |
| R-05 | Object storage webhook: remove /internal/s3-event endpoint entirely | R-03 |
| R-06 | connectors CRUD API (POST/GET/PATCH/DELETE /api/connectors); DELETE cascades soft-delete to all associated documents | R-01 |
| R-07 | Connector sync API (POST /sync, GET /sync/status, GET /docs) + BackgroundTasks dispatch | R-06 |
| R-08 | parse_op: new format support — HTML (doc_type=html, LlamaIndex HTML reader, strip nav/footer/script) and RST (doc_type=rst, LlamaIndex RST reader or plain-text fallback) | R-04 |
| R-09 | WebConnector implementation (Trafilatura + httpx, URL normalization, content_version via HTTP ETag) | R-07, R-04, R-08 |
| R-10 | ConfluenceConnector implementation | R-07, R-04 |
| R-11 | GitHubConnector implementation | R-07, R-04, R-08 |
| R-12 | Connector Dagster Schedule dynamic registration | R-09 |

Recommended implementation order: R-01 -> R-02 -> R-03 + R-04 (coordinated deploy) -> R-05 -> R-06 -> R-07 -> R-08 -> R-09 (core complete)
