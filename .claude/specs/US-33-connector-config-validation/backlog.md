# US-33 Connector Config Numeric Field Validation

## Problem

Connector config is stored as `dict[str, Any]` with no type or range validation at the API layer.

- Passing a string for `depth`, `max_pages`, etc. returns 201/200 with no error
- The value is saved to DB as-is (string)
- At sync time, `int("abc")` raises `ValueError`, caught by `_run_sync`'s broad exception handler → connector `status=error` with no HTTP error returned
- `min_content_chars` default is hardcoded in `web.py` instead of `settings.yaml`

## Acceptance Criteria

- Passing a non-integer value for a known numeric config field returns HTTP 422
- Passing an out-of-range value for a known numeric config field returns HTTP 422
- `min_content_chars` default is read from `settings.yaml` (`ingestion.min_content_chars: 200`)
- Per-connector config can still override `min_content_chars`

## Scope

### Numeric field limits

| Field | Source type | min | max |
|-------|-------------|-----|-----|
| `depth` | web, confluence | 1 | 10 |
| `max_pages` | web, confluence | 1 | 500 |
| `request_timeout_sec` | web | 1 | 300 |
| `request_delay_ms` | web | 0 | 5000 |
| `min_content_chars` | web | 0 | 10000 |

### Files to change

- `src/api/routers/connectors.py` — add `_validate_connector_int_fields()`, call in `validate_config` and `validate_patch`
- `src/config/settings.py` — add `min_content_chars: int = 200` to `IngestionSettings`
- `settings.yaml` + `settings.example.yaml` — add `min_content_chars: 200` under `ingestion`
- `src/connectors/web.py` — use `get_settings().ingestion.min_content_chars` as default

## Notes

- `ConnectorPatch` does not carry `source_type`, so PATCH validates against the union of all known int fields
- `confluence.depth` is optional (None = unlimited); only validate if key is present in config
