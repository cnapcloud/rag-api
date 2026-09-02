# Frontend Design — RAG API Admin UI

## Overview

Single-page admin UI for managing knowledge bases, monitoring document ingestion, and running search queries.
Style reference: minimal sidebar-icon layout (LibreChat admin style).

---

## Navigation

```
+------+------------------------------------------+
| icon | page                                      |
+------+------------------------------------------+
| HOME | Dashboard (health status)                 |
|  KB  | Knowledge Bases                           |
| DOCS | Documents (embedding status)              |
| SRCH | Query                                     |
+------+------------------------------------------+
```

Sidebar collapses to icons only. Active icon is highlighted.

---

## Pages

### 1. Home

Displays infrastructure readiness from `GET /ready`.

```
+--------------------------------------------------------+
| Welcome                                                |
|                                                        |
|  Qdrant    [OK]    Redis     [OK]                      |
|  S3        [OK]    Postgres  [OK]                      |
|  <provider> [OK]           (label = "provider" field)  |
+--------------------------------------------------------+
```

API: `GET /ready`

Response shape:
```json
{
  "status": "ready",
  "provider": "ollama",
  "checks": {
    "qdrant": true,
    "redis": true,
    "postgres": true,
    "s3": true,
    "ollama": true
  }
}
```

- `provider` (top-level) is always present — the configured embedding provider name (`ollama` / `openai` / `jina` / any custom name). Use it as the label for the provider tile.
- The provider probe result is under `checks[<provider>]` (the same string as the `provider` field). Every provider is probed the same way — `GET {v1_base}/models` on its OpenAI-compatible endpoint — and counts toward overall readiness (a failure flips `status` to `not_ready` / 503).
- The only case with no provider key is a custom `name` configured without a `url` (a misconfiguration). Show the tile labeled by `provider` with a neutral "not checked" state — do not treat the missing key as a failure.

---

### 2. Knowledge Bases

```
+--------------------------------------------------------+
| Knowledge Bases                          [+ New KB]    |
|                                                        |
| [ Search...                         ]                  |
|                                                        |
|  Name           Description          Tags    Status    |
|  ─────────────────────────────────────────────────     |
|  kb-01          Production docs fo…  [prod]  Active    |
|  kb-02          Dev reference        []      Active    |
|                                                        |
| (row click) → detail panel: id, name, desc, tags,     |
|              created_at   [Edit] [Delete]              |
+--------------------------------------------------------+
```

| Action | API |
|--------|-----|
| List | `GET /api/kb` — returns `kb_id`, `kb_name`, `description`, `tags`, `status`, `created_at` |
| Detail | `GET /api/kb/{kb_id}` — same fields as list item, used for detail panel |
| Create | `POST /api/kb` — body: `kb_id`, `kb_name`, `description`, `tags` |
| Delete | `DELETE /api/kb/{kb_id}` — confirms cascade (Qdrant + S3 + Postgres) |

Create modal fields:

| Field | Required | Note |
|-------|----------|------|
| KB ID | yes | slug, no spaces |
| Name | no | display label |
| Description | no | |
| Tags | no | comma-separated |

---

### 3. Documents

```
+--------------------------------------------------------+
| Documents               [Upload]  [Reindex All]        |
|                                                        |
| KB: [kb-01 ▼]  Status: [All ▼]  Sort: [Updated ▼] [↓]  |
| [ Search source...                                  ]  |
|                                                        |
| [ ] Source            Status   Chunks  Age             |
| ─────────────────────────────────────────────────────  |
| [x] report-2024.pdf   indexed  42      2h              |
| [ ] manual.docx       running  —       5m              |
| [x] draft.txt         failed   0       1d              |
|     ...                                                |
|                                                        |
|  (selection toolbar, appears when >0 checked)          |
|  [ Reindex Selected ]  [ Delete Selected ]             |
|                                                        |
|  Showing 1-20 of 87       [<] [1] [2] [3] [4] [5] [>]  |
+--------------------------------------------------------+
```

KB filter: always scoped to a single KB — no "All" option. Defaults to the first KB returned by `GET /api/kb` on page load. Switching KB resets pagination and document list.
[Reindex All] applies to the currently selected KB only.
Search performs a substring (contains) match on `doc_source` — matches filename and path segments.
Sort dropdown options: Updated (default desc), Created, Name, Chunks, Size. Direction toggle [↑][↓].

Pagination: `GET /api/kb/{kb_id}/docs` returns paginated results (default page=1, page_size=20, max 100). Query params: `page`, `page_size`, `status`, `search`, `sort_by`, `sort_order`.
Page group window: shows 5 page numbers at a time. `[<]` / `[>]` move to the previous/next group of 5. Clicking a number navigates to that page. All group calculation is frontend-only — backend returns `total`, `page`, `page_size`.

Response shape:
```json
{ "items": [...], "total": 87, "page": 1, "page_size": 20 }
```
Each item: `doc_source`, `status`, `doc_type`, `chunk_count`, `file_size`, `embedding_model`, `last_error`, `created_at`, `updated_at`, `etag`.
`etag` is an internal S3 dedup hash — do not display in the UI.

Status badge colors: `indexed` = green, `running` = blue, `pending` = gray, `failed` = red.

Clicking a row opens a detail panel:

```
  doc_source   report-2024.pdf
  kb_id        kb-01
  status       indexed
  doc_type     pdf
  chunk_count  42
  file_size    1.2 MB
  embedding_model  ollama/nomic-embed-text
  updated_at   2026-06-19 14:32
  last_error   —
  [Reindex]  [Recover]  [Delete]
```

`Recover` visible only when `status = running` AND `updated_at` is older than 30 minutes.
A recently-updated `running` document is likely still processing — show a spinner instead.
The 30-minute threshold should be a frontend config constant, not hardcoded.

| Action | API |
|--------|-----|
| List (paginated) | `GET /api/kb/{kb_id}/docs?page=1&page_size=20` |
| List (filtered) | `GET /api/kb/{kb_id}/docs?status=failed&search=report&sort_by=updated_at&sort_order=desc` |
| Upload single | `POST /api/kb/{kb_id}/docs/upload` — response: `{ doc_source, status_url, etag }` |
| Upload batch | `POST /api/kb/{kb_id}/docs/upload/batch` — response: `{ results: [{ doc_source, status_url, etag }] }` |
| Delete | `DELETE /api/kb/{kb_id}/docs/{source}` |
| Reindex selected | `POST /api/kb/{kb_id}/docs/reindex?source={source}` per item (`&force=true` to force re-embed) |
| Reindex all | `POST /api/kb/{kb_id}/reindex` (`?force=true` to skip ETag comparison) |
| Recover stuck | `POST /api/kb/{kb_id}/docs/{source}/recover` — only valid when `status=running` |
| Status poll | `GET /api/kb/{kb_id}/docs/{source}/status` (poll during `running`) |

Upload flow: file picker (multi-select) → batch upload → auto-poll status every 5 s until `indexed` or `failed`.

#### Upload Modal

Triggered by the [Upload] button. KB is pre-selected from the active KB filter (always a specific KB, never "All").

```
+--------------------------------------------+
| Upload Documents                       [x] |
|                                            |
| KB  [kb-01 ▼]                              |
|                                            |
| +----------------------------------------+ |
| |                                        | |
| |   Drag & drop files here               | |
| |   or  [ Browse ]                       | |
| |                                        | |
| |   Supported: pdf, docx, txt, md, hwp   | |
| +----------------------------------------+ |
|                                            |
| report-2024.pdf      1.2 MB   [x]         |
| manual.docx          340 KB   [x]         |
|                                            |
|              [Cancel]  [Upload]            |
+--------------------------------------------+
```

After [Upload]:

```
+--------------------------------------------+
| Upload Documents                       [x] |
|                                            |
| report-2024.pdf   [===========] indexed   |
| manual.docx       [======     ] running   |
|                                            |
|                              [Close]       |
+--------------------------------------------+
```

Progress bar polls `GET /api/kb/{kb_id}/docs/{source}/status` every 5 s per file.
[Close] enabled once all files reach `indexed` or `failed`.

---

### 4. Query

```
+--------------------------------------------------------+
| Query                                                  |
|                                                        |
| KBs:  [kb-01 x] [kb-02 x]  [+ Add KB]                 |
|                                                        |
| [ Query text...                                   ]    |
|                                                        |
| Mode:  (o) hybrid   ( ) similarity                     |
|                                                        |
| Options:                                               |
|   top_k      [ 10 ]                                    |
|   alpha      [ 0.5 ]      (hybrid only)                |
|   min_score  [ 0.70 ]     (similarity only)            |
|   Rerank     [x] enabled   top_n [ 5 ]                 |
|                                            [ Search ]  |
+--------------------------------------------------------+
| Results  (8 found, 5 returned)   142 ms   reranked     |
|                                                        |
| 1.  score 0.94   kb-01 / report-2024.pdf   p.3         |
|    "...relevant excerpt from the document..."          |
|                                                        |
| 2.  score 0.88   kb-02 / manual.docx                   |
|    "...another excerpt..."                             |
+--------------------------------------------------------+
```

Request body mapped from UI:

```json
{
  "query": "<input>",
  "kb_ids": ["kb-01", "kb-02"],
  "options": {
    "mode": "hybrid",
    "top_k": 10,
    "hybrid": { "alpha": 0.5 },
    "similarity": { "min_score": 0.7 },
    "rerank": { "enabled": true, "top_n": 5 }
  }
}
```

Result card shows: rank, score / rerank_score, kb_id, doc_source (human-readable path), page_num / page_label (if present), text excerpt.
`doc_key` (`{kb_id}___{doc_source}`) is available in the response but should not be displayed raw — use `doc_source` for display.

Meta bar shows: `total_candidates`, `returned`, `latency_ms`, `reranked`, `search_mode`, `rerank_fallback`.
`rerank_fallback: true` means the reranker API failed and RRF scores were used instead — indicate this with a visual hint (e.g. "reranked (fallback)").
Additional response fields available if needed: `score_threshold`, `rerank_provider`.

API: `POST /api/search`

---

## Component Inventory

| Component | Used on |
|-----------|---------|
| Sidebar (icon + label, collapsible) | all |
| StatusBadge (indexed / running / pending / failed) | Docs |
| DataTable (sortable, row-select checkboxes) | KB, Docs |
| DetailPanel (slide-in or right column) | KB, Docs |
| FileUploadDropzone (multi-file) | Docs |
| KBMultiSelect (tag-style picker) | Query |
| SearchOptionsPanel (mode toggle + numeric inputs) | Query |
| ResultCard (score + excerpt) | Query |
| ConfirmDialog (delete) | KB, Docs |
| HealthGrid (status tiles: Qdrant/Redis/S3/Postgres + optional Ollama) | Home |

---

## Supported File Types

`.pdf` `.docx` `.txt` `.md` `.hwp`

Validated server-side; UI shows the same list as a hint on the upload dropzone.
