# Plan 13 — Document List API: Pagination / Search / Sort

Implements US-13.

## Overview

Extend `GET /api/kb/{kb_id}/docs` to support pagination, substring search on `doc_source`,
status filtering, and sorting. All query runs against the Postgres `documents` table.

## Changes

### 1. `src/infra/postgres.py` — new function `list_docs_paginated`

```
list_docs_paginated(
    kb_id, page, page_size, status=None, search=None,
    sort_by="updated_at", sort_order="desc"
) -> tuple[list[dict], int]
```

- Two SQL queries: COUNT(*) then paginated SELECT.
- `search` → `doc_source ILIKE '%value%'`
- `sort_by` in `{chunk_count, file_size}` → append `NULLS LAST` regardless of direction.
- `LIMIT page_size OFFSET (page-1)*page_size`
- Response dict fields typed correctly: `chunk_count: int|None`, `file_size: int|None`, `error: str|None`.

### 2. `src/api/routers/docs.py` — update `list_docs`

- Accept 6 query params: `page`, `page_size`, `status`, `search`, `sort_by`, `sort_order`.
- `sort_by` / `sort_order` validated via `Literal` type annotations.
- `page_size` silently clamped to 100 server-side (`min(page_size, 100)`).
- Response: `{items, total, page, page_size}`.
- Remove old `list_docs_by_status` call (merged into `list_docs_paginated`).

### 3. `tests/conftest.py` — extend `FakePostgresStore`

Add `list_docs_paginated` method with Python-level filtering/sorting/pagination logic
so router tests can use the fixture without a real DB.

Add `monkeypatch.setattr("infra.postgres.list_docs_paginated", ...)` in `mock_postgres`.

### 4. `tests/unit/test_doc_list_api.py` — new test file

Cases:
- Default response shape (items/total/page/page_size)
- `page=2` returns correct slice
- Out-of-range page → empty items, correct total
- `page_size` > 100 silently clamped to 100
- `search` substring filter (case-insensitive)
- `status` filter
- `sort_by=doc_source&sort_order=asc`
- Invalid `sort_by` → 422

## Constraints

- `sort_by` injection is prevented by Pydantic `Literal` validation (only 5 allowed values).
- `list_docs_by_status` in postgres.py kept for backward compatibility (used by reindex logic? — check: no, only `list_docs` used by reindex). Keep for now, mark as unused.
- Existing `GET /api/kb/{kb_id}/docs` response format changes (breaking): callers must be updated.
  The `/docs/status` endpoint and reindex endpoint use `infra.postgres.list_docs` directly — unaffected.
