"""validate Op — ETag duplicate check and file size guard."""

from __future__ import annotations

import logging

from config.settings import get_settings
from exceptions import IngestValidationError
from infra import postgres as postgres_infra

logger = logging.getLogger(__name__)


def validate(kb_id: str, doc_source: str, etag: str, file_size: int = 0, force: bool = False) -> bool:
    """
    Returns:
        True  -> proceed
        False -> skip (ETag unchanged)

    Raises:
        IngestValidationError: file too large
    """
    cfg = get_settings()
    max_bytes = cfg.ingestion.max_file_size_mb * 1024 * 1024

    if file_size > 0 and file_size > max_bytes:
        raise IngestValidationError(
            f"File too large: {file_size / 1024 / 1024:.1f} MB > {cfg.ingestion.max_file_size_mb} MB"
        )

    if not force:
        stored_etag = postgres_infra.get_doc_etag(kb_id, doc_source)
        if stored_etag and stored_etag == etag:
            logger.info("ETag unchanged, skipping: kb=%s key=%s etag=%s", kb_id, doc_source, etag)
            return False

    logger.info("Validation passed: kb=%s key=%s etag=%s force=%s", kb_id, doc_source, etag, force)
    return True
