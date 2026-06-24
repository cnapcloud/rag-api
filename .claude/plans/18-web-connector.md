# Plan 18 — WebConnector (R-09)

**Covers**: US-18
**Status**: in-progress

---

## Architecture

```
_dispatch_sync (connectors.py)
  └── WebConnector(config).sync(kb_id, connector_id)
        ├── BFS queue: [(normalized_url, depth)]
        ├── per URL: _process_page(client, kb_id, connector_id, source_uri) -> html | None
        │     ├── lookup: get_doc_by_source_uri()
        │     ├── GET page via httpx
        │     ├── ETag comparison -> skip if unchanged (return html for link discovery)
        │     ├── create_doc() or update_doc_fields(status=fetching)
        │     ├── _extract_title(html) via trafilatura.extract_metadata + BS4 fallback
        │     ├── upload_object() -> S3 staging
        │     ├── update_doc_fields(status=pending, storage_key, content_version, ...)
        │     └── enqueue_upload_event(doc_id)
        └── _discover_links(html, base_url) -> [abs_url] via BeautifulSoup
```

## New Files

### `src/connectors/__init__.py`
Empty package init.

### `src/connectors/web.py`

```python
class WebConnector:
    def __init__(self, config: dict) -> None: ...
    def sync(self, kb_id: str, connector_id: str) -> None: ...
    def _should_process(self, url: str) -> bool: ...
    def _process_page(self, client, kb_id, connector_id, source_uri) -> str | None: ...
    def _discover_links(self, html: str, base_url: str) -> list[str]: ...

def _extract_title(html: str, fallback: str) -> str:
    # trafilatura.extract_metadata(html).title -> BS4 <title> -> fallback
```

Key behaviours:
- Always GET (never HEAD) — ensures link discovery works on re-syncs
- ETag comparison happens AFTER the GET response is received
- Unchanged pages return html but skip staging/enqueue
- Failed GET: if doc exists, set failed; if new, create doc with status=failed

## Changed Files

### `src/api/routers/connectors.py`

Replace placeholder `_dispatch_sync`:
```python
def _dispatch_sync(connector: dict) -> None:
    source_type = connector["source_type"]
    if source_type == "web":
        from connectors.web import WebConnector
        WebConnector(connector.get("config") or {}).sync(
            connector["kb_id"], connector["connector_id"]
        )
    else:
        raise ConfigError(f"connector type not yet implemented: {source_type}")
```

## Tests

`tests/unit/test_web_connector.py` — mock httpx.Client, postgres, s3, enqueue.

Test cases:
- new page → creates doc, stages, enqueues
- existing page, same ETag → skips (returns html for link discovery)
- existing page, changed ETag → restages, re-enqueues
- deleted page → re-fetches
- GET failure → status=failed, returns None
- S3 failure → status=failed, returns html
- include_patterns filter
- exclude_patterns filter
- max_pages limit
- BFS depth: links discovered from depth-0 pages are queued at depth-1

## Dependencies

- `trafilatura>=0.9.0` added to `pyproject.toml`
- `httpx` already in dependencies
- `bs4` already installed (transitive)
