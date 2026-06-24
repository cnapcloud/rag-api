---
id: US-18
title: WebConnector implementation (R-09)
status: in-progress
requirement: docs/dev/requirement-multi-source-ingest.md — R-09
---

## User Story

As an operator, I want to configure a web connector that crawls seed URLs and
automatically indexes HTML pages into a knowledge base, so that web content is
kept up to date without manual uploads.

## Background

R-09 specifies: WebConnector implementation (Trafilatura + httpx, URL normalization,
content_version via HTTP ETag).

The connector framework (US-16) provides the API layer and background dispatch stub.
This item implements the `web` source_type connector that replaces the stub.

## Flow B Implementation (per page)

1. Normalize URL via `pipeline.source_uri.normalize_source_uri("web", url)`
2. Lookup by (kb_id, source_uri) in documents table
   - not found: create row (status=fetching, doc_type=html)
   - deleted: set status=fetching
   - other: compare stored content_version with HTTP ETag — skip if unchanged
3. GET full page content (always, to enable link discovery for BFS)
   - failure: set status=failed, continue
4. Extract title via trafilatura.extract_metadata(); fallback to `<title>` tag
5. Stage raw HTML to S3: `{kb_id}/web/{doc_id}.html`
   - failure: set status=failed, return html for link discovery
6. Update doc: status=pending, storage_key, content_version (HTTP ETag), file_size, source (title)
7. Enqueue {doc_id, force=false}

BFS crawl: seed_urls at depth 0, extract links via BeautifulSoup, follow up to
`depth` levels, respecting `include_patterns` / `exclude_patterns` (fnmatch),
stopping at `max_pages`.

## Scope

- `src/connectors/__init__.py` (empty package init)
- `src/connectors/web.py` — `WebConnector` class
- `src/api/routers/connectors.py` — replace stub `_dispatch_sync` with WebConnector dispatch
- `pyproject.toml` — add `trafilatura>=0.9.0`
- `tests/unit/test_web_connector.py`

## Out of Scope

- ConfluenceConnector (R-10), GitHubConnector (R-11)
- Dagster Schedule dynamic registration (R-12)
- robots.txt compliance (future)

## Acceptance Criteria

- [ ] New URL: creates doc row (fetching), fetches, stages .html to S3, enqueues, status=pending
- [ ] Existing URL, same ETag: skips staging and enqueue; HTML still returned for link discovery
- [ ] Existing URL, changed ETag: re-stages and re-enqueues
- [ ] Deleted URL: sets fetching, re-fetches
- [ ] HTTP fetch failure: sets status=failed, continues to next page
- [ ] S3 stage failure: sets status=failed, continues
- [ ] include_patterns filters non-matching URLs
- [ ] exclude_patterns blocks matching URLs
- [ ] max_pages stops crawl after limit
- [ ] BFS discovers links up to configured depth
- [ ] `_dispatch_sync` calls WebConnector for source_type="web"; raises ConfigError for others
- [ ] All tests use mocked httpx, postgres, s3, enqueue (no real connections)
