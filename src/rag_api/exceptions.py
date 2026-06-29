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
