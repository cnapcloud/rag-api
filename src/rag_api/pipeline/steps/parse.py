"""parse Op — LlamaIndex SimpleDirectoryReader-based document parsing."""

from __future__ import annotations

import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from llama_index.core import Document, SimpleDirectoryReader

from rag_api.exceptions import IngestValidationError
from rag_api.infra.s3 import download_by_key

logger = logging.getLogger(__name__)


def supported_extensions() -> frozenset[str]:
    """All parseable extensions — registry-managed formats (see pipeline/steps/parser/)."""
    from rag_api.pipeline.steps import parser

    return parser.supported_extensions()


def _extract_doc_created_at(file_path: Path, suffix: str, storage_key: str) -> str:
    """Extract document creation date from file metadata.

    Priority: PDF CreationDate / DOCX/PPTX core_properties.created -> S3 LastModified fallback.
    Returns an ISO 8601 UTC string, or empty string if all sources fail.
    """
    dt: datetime | None = None

    try:
        if suffix == ".pdf":
            import pypdf

            reader = pypdf.PdfReader(str(file_path))
            if reader.metadata and reader.metadata.creation_date:
                raw = reader.metadata.creation_date
                dt = raw if isinstance(raw, datetime) else None
        elif suffix == ".docx":
            import docx

            doc = docx.Document(str(file_path))
            created = doc.core_properties.created
            if created:
                dt = created if isinstance(created, datetime) else None
        elif suffix == ".pptx":
            from pptx import Presentation

            prs = Presentation(str(file_path))
            created = prs.core_properties.created
            if created:
                dt = created if isinstance(created, datetime) else None
    except Exception as e:
        logger.debug("doc_created_at extraction failed (will fallback): file=%s err=%s", file_path.name, e)

    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()

    try:
        from rag_api.infra.s3 import get_object_last_modified_by_key

        return get_object_last_modified_by_key(storage_key)
    except Exception as e:
        logger.debug("S3 LastModified fallback failed: storage_key=%s err=%s", storage_key, e)
        return ""


def parse(doc_id: str, storage_key: str, local_path: Path | None = None) -> list[Document]:
    """Download a file from S3 and return a list of LlamaIndex Documents.

    Args:
        doc_id: UUID of the document row (used to tag metadata).
        storage_key: Full S3 object path (e.g. 'kb-01/report.pdf').
        local_path: Pre-downloaded local file (for tests / CLI use).
    """
    from rag_api.pipeline.steps import parser

    suffix = Path(storage_key).suffix.lower()
    if suffix not in supported_extensions():
        raise IngestValidationError(f"Unsupported file format: {suffix}")

    with tempfile.TemporaryDirectory() as tmpdir:
        if local_path is None:
            dest = Path(tmpdir) / Path(storage_key).name
            download_by_key(storage_key, dest)
            file_path = dest
        else:
            file_path = local_path

        parsers = parser.get_parsers()
        reader = SimpleDirectoryReader(
            input_files=[str(file_path)],
            file_extractor=parsers if parsers else None,
        )
        documents = reader.load_data()

        for post_process in parser.get_post_processors():
            documents.extend(post_process(documents, file_path, suffix))

        doc_created_at = _extract_doc_created_at(file_path, suffix, storage_key)

        for doc in documents:
            doc.metadata.update(
                {
                    "doc_id": doc_id,
                    "doc_type": suffix.lstrip("."),
                    "doc_created_at": doc_created_at,
                }
            )

        logger.info(
            "Parsed: doc_id=%s storage_key=%s documents=%d doc_created_at=%s",
            doc_id, storage_key, len(documents), doc_created_at or "n/a",
        )
        return documents


def parse_local(file_path: Path, doc_id: str = "local", storage_key: str | None = None) -> list[Document]:
    """Parse a local file directly (CLI / test use)."""
    key = storage_key or file_path.name
    return parse(doc_id=doc_id, storage_key=key, local_path=file_path)
