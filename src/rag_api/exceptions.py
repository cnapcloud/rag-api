"""Domain exception hierarchy for the RAG API.

Only exceptions with business-level meaning are defined here.
Library exceptions (S3Error, RedisError) are registered directly
in api/app.py and propagate without wrapping.
"""

from __future__ import annotations


class RAGError(Exception):
    """Base class for all domain exceptions."""


class ConfigError(RAGError):
    """Invalid or inconsistent configuration (e.g. vector_size mismatch). Maps to HTTP 500."""


class IngestValidationError(RAGError):
    """Pipeline-level validation failed (file size, unsupported format, etc.). Maps to HTTP 422."""


class NotFoundError(RAGError):
    """Requested KB or document does not exist. Maps to HTTP 404."""


class ConflictError(RAGError):
    """Resource already exists. Maps to HTTP 409."""


class HookAbort(Exception):
    """A registered pipeline hook callback deliberately stopped the pipeline action.

    Intentionally NOT a subclass of RAGError: this is a separate axis from the
    layered domain hierarchy above. Vendoring packages subclass it (e.g. a
    document-quota error) and capture points catch HookAbort, not the concrete
    subclass. Re-exported from rag_api.hooks. Maps to HTTP 403.
    """


class BatchUploadError(Exception):
    """A batch document upload finished with at least one failed item.

    Intentionally NOT a RAGError: like HookAbort this is a transport-level signal,
    not a domain layer. The batch route processes every file (collect-and-continue)
    and raises this once the loop is done if any item failed, so the response can
    carry a non-2xx status without losing the per-item outcomes.

    - ``results``: the full per-item list (ok entries + ``{title, error, status}``),
      1:1 with the submitted files.
    - ``detail``: the first real failure reason, verbatim, for a one-line UI message.
    - ``by_hook``: True when a pipeline hook stopped the batch -> HTTP 403 (mirrors a
      single upload); False for per-item validation/storage failures -> HTTP 422.
    """

    def __init__(self, results: list[dict], *, detail: str, by_hook: bool) -> None:
        self.results = results
        self.detail = detail
        self.by_hook = by_hook
        super().__init__(detail)
