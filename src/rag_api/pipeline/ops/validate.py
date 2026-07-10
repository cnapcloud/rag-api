"""validate Op — file size guard before ingest."""

from __future__ import annotations

import logging

from rag_api.config.settings import get_settings
from rag_api.exceptions import IngestValidationError

logger = logging.getLogger(__name__)


def validate(doc_id: str, force: bool = False) -> bool:
    """
    Returns:
        True  -> proceed
        False -> skip (not currently used, reserved for future skip logic)

    Raises:
        IngestValidationError: document not found or file too large
    """
    from rag_api.infra.postgres import get_doc_by_id

    doc = get_doc_by_id(doc_id)
    if doc is None:
        raise IngestValidationError(f"Document not found: doc_id={doc_id}")

    cfg = get_settings()
    max_bytes = cfg.ingestion.max_file_size_mb * 1024 * 1024
    file_size = doc.get("file_size") or 0
    if file_size > 0 and file_size > max_bytes:
        raise IngestValidationError(
            f"File too large: {file_size / 1024 / 1024:.1f} MB > {cfg.ingestion.max_file_size_mb} MB"
        )

    logger.info("Validation passed: doc_id=%s force=%s", doc_id, force)
    return True
