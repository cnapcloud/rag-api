---
paths:
  - "src/**/*.py"
---

# Exception Handling Convention

## Exception Hierarchy

```
RAGError (base)
├── ConfigError           → HTTP 500  Invalid/inconsistent configuration
├── IngestValidationError → HTTP 422  Pipeline validation failed
├── NotFoundError         → HTTP 404  KB or document not found
└── ConflictError         → HTTP 409  Resource already exists
```

Library exceptions are registered **directly** in `api/app.py` without intermediate wrapper classes:

| Exception | HTTP | Source |
|-----------|------|--------|
| `minio.error.S3Error` | 502 | MinIO |
| `redis.RedisError` | 503 | Redis |

All classes defined in `src/exceptions.py`. Never define exception classes elsewhere.

---

## Layer Rules

### infra/ (minio.py, qdrant.py, redis.py)

- Do **not** wrap library exceptions into domain exceptions. Let `S3Error`, `RedisError`, etc. propagate as-is.
- `ping()` functions are exempt: return `bool`, swallow internally.
- Only raise `ConfigError` for configuration-level errors detectable at the infra layer (e.g. vector_size mismatch in `ensure_collection`).

```python
# minio.py — no wrapping
def upload_object(...) -> str:
    result = client.put_object(...)   # S3Error propagates freely → app.py maps to 502
    return (result.etag or "").strip('"')
```

### pipeline/steps/ (validate.py, parse.py, chunk.py, embed.py)

- Pure functions — no HTTP knowledge, no `HTTPException`.
- Raise `IngestValidationError` for user-fixable input errors (bad format, file too large).
- Raise `ConfigError` for operator-fixable configuration errors (wrong provider).
- Never raise bare `ValueError`.

```python
# validate.py
if file_size > max_bytes:
    raise IngestValidationError(f"File too large: {size_mb:.1f} MB > {max_mb} MB")
```

### api/routers/

- Never catch `Exception` broadly.
- Raise `NotFoundError` or `ConflictError` for business-level 404/409.
- Catch `S3Error` **only** in the one place where the business decision is to swallow it (silent-fail delete).
- All other exceptions propagate to global handlers in `app.py`.

```python
# docs.py: MinIO delete after Qdrant/Redis cleanup — intentionally swallowed
from minio.error import S3Error

try:
    delete_object(kb_id, key)
except S3Error as e:
    logger.warning("MinIO object deletion failed (ignored): kb=%s key=%s err=%s", kb_id, key, e)
```

### api/app.py

Global exception handlers map exceptions to HTTP responses.
**HTTP status code assignment lives exclusively here — not in routers or infra.**

---

## Silent-Fail Policy

| Scenario | Policy |
|----------|--------|
| MinIO delete after Qdrant/Redis cleanup succeeded | Log warning, return 200 |
| Startup infrastructure init failure | Log warning, continue startup |
| Single KB failure during multi-KB search | Log error, return empty for that KB |
| Reranker API failure with `fallback_on_error=true` | Log warning, use RRF score fallback |

All other failures propagate.

---

## Message Rules

- All exception messages in English.
- Include relevant context (`kb_id`, `doc_source`) where available.
- `from e` chaining is mandatory — never `raise DomainError(...) from None`.
- No silent swallowing outside the explicit silent-fail policy above.

```python
# Correct
raise IngestValidationError(f"File too large: {size_mb:.1f} MB > {max_mb} MB")
raise ConfigError(f"Unknown chunking strategy: {strategy}")

# Wrong — missing from e, Korean message
raise ConfigError("청킹 전략 오류")
```
