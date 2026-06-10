"""validate Op — ETag 중복 체크 및 파일 크기 제한."""

from __future__ import annotations

import logging

from config.settings import get_settings
from exceptions import IngestValidationError
from infra import redis as redis_infra

logger = logging.getLogger(__name__)


def validate(kb_id: str, object_key: str, etag: str, file_size: int = 0, force: bool = False) -> bool:
    """
    Returns:
        True  → proceed
        False → skip (ETag unchanged or already processing)

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
        stored_etag = redis_infra.get_doc_etag(kb_id, object_key)
        if stored_etag and stored_etag == etag:
            logger.info("ETag unchanged, skipping: kb=%s key=%s etag=%s", kb_id, object_key, etag)
            return False

    logger.info("Validation passed: kb=%s key=%s etag=%s force=%s", kb_id, object_key, etag, force)
    return True