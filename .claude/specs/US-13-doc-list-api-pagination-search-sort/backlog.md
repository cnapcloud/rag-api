# US-13 — Document List API: Pagination / Search / Sort

## Goal

Extend `GET /api/kb/{kb_id}/docs` to support pagination, substring search on `doc_source`, status filtering, and sorting. Required before the Documents page frontend can be implemented.

## Current State

The endpoint returns all documents for a KB in a single response with no filtering or pagination.

## Requirements

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | int | 1 | Page number (1-based) |
| `page_size` | int | 20 | Items per page (max: 100) |
| `status` | str | — | Filter by status: `running`, `indexed`, `failed`, `deleting` |
| `search` | str | — | Substring (contains) match on `doc_source` (case-insensitive) |
| `sort_by` | str | `updated_at` | Sort field: `updated_at`, `created_at`, `doc_source`, `chunk_count`, `file_size` |
| `sort_order` | str | `desc` | Sort direction: `asc`, `desc` |

### Response Body

```json
{
  "items": [
    {
      "doc_source": "reports/2024/report.pdf",
      "status": "indexed",
      "doc_type": "pdf",
      "chunk_count": 42,
      "file_size": 1258291,
      "embedding_model": "ollama/nomic-embed-text",
      "error": null,
      "created_at": "2026-06-19T14:30:00Z",
      "updated_at": "2026-06-19T14:32:00Z"
    }
  ],
  "total": 87,
  "page": 1,
  "page_size": 20
}
```

### Existing Single-Doc Endpoint

`GET /api/kb/{kb_id}/docs/{key}` (detail + status poll) remains unchanged.

## Implementation Notes

- Query runs against Postgres `documents` table.
- `search` uses `ILIKE '%value%'` on `doc_source`.
- `sort_by=chunk_count` or `file_size`: `NULL` rows sort last regardless of direction.
- `page` out of range returns empty `items` list (not 404).
- `page_size` capped at 100 server-side; excess silently clamped.

## Acceptance Criteria

- [ ] All 6 query parameters accepted and validated (Pydantic).
- [ ] Response schema matches above structure.
- [ ] `total` reflects filtered count (not total in KB).
- [ ] `search` is case-insensitive substring match on `doc_source`.
- [ ] `sort_by` NULL-last behavior for numeric fields.
- [ ] Unit tests: pagination math, search filter, sort order, out-of-range page.
- [ ] Existing `GET /api/kb/{kb_id}/docs` callers (if any) updated or remain compatible.
