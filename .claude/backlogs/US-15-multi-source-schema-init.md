---
id: US-15
title: Multi-source ingest schema initialization (R-01)
status: todo
requirement: docs/dev/requirement-multi-source-ingest.md — R-01
---

## User Story

As a developer beginning the multi-source ingest implementation,
I want the Postgres schema freshly initialized with the full new design,
so that all subsequent R items (R-02 through R-11) can build on a correct foundation.

## Scope

- Drop and recreate `documents`, `connectors`, `simhash_bands` tables with new schema
- Replace `infra/postgres.py` document CRUD to be doc_id-based
- Update `docs/dev/data-schema.md` to reflect new schema

## Out of Scope

- Connector CRUD API (R-06)
- Upload flow changes (R-03)
- Pipeline doc_id conversion (R-04)
- source_uri normalization logic (R-02)

## Acceptance Criteria

- [ ] New DDL applies cleanly on a fresh Postgres instance
- [ ] `documents` table: `doc_id UUID PRIMARY KEY`, `UNIQUE(kb_id, source_uri)`, all new fields (source_type, source_uri, storage_key, content_version, connector_id, deleted_at, process_started_at, process_finished_at), extended status set
- [ ] `connectors` table created with all fields
- [ ] `simhash_bands` table: `band_id UUID PRIMARY KEY`, `doc_id UUID FK`
- [ ] `infra/postgres.py` exposes: `upsert_doc`, `get_doc_by_id`, `get_doc_by_source_uri`, `update_doc_fields`, `soft_delete_doc`, `list_docs` with soft-delete filter, `list_docs_paginated` updated
- [ ] Deprecated functions removed: `set_doc_status`, `get_doc_etag`, `set_doc_etag`, `delete_doc_etag`, `delete_doc_meta` (hard delete)
- [ ] Unit tests pass for all new CRUD functions
- [ ] `docs/dev/data-schema.md` reflects new schema
