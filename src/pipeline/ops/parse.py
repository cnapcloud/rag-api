"""parse Op — LlamaIndex SimpleDirectoryReader 기반 문서 파싱."""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from llama_index.core import Document, SimpleDirectoryReader

from exceptions import IngestValidationError
from infra.s3 import download_object

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".docx", ".txt", ".hwp"}


def _extract_doc_created_at(file_path: Path, suffix: str, kb_id: str, object_key: str) -> str:
    """Extract document creation date from file metadata.

    Priority: PDF CreationDate / DOCX core_properties.created → S3 LastModified fallback.
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
    except Exception as e:
        logger.debug("doc_created_at extraction failed (will fallback): file=%s err=%s", file_path.name, e)

    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()

    # Fallback: S3 LastModified
    try:
        from infra.s3 import get_object_last_modified

        return get_object_last_modified(kb_id, object_key)
    except Exception as e:
        logger.debug("S3 LastModified fallback failed: kb=%s key=%s err=%s", kb_id, object_key, e)
        return ""


def _get_file_extractor() -> dict:
    """파일 확장자별 LlamaIndex 리더 매핑."""
    try:
        from llama_index.readers.file import DocxReader, FlatReader, MarkdownReader, PDFReader
        from llama_index.readers.hwp import HWPReader
    except ImportError:
        logger.warning("llama-index-readers-file not installed, using default reader")
        return {}

    return {
        ".pdf": PDFReader(),
        ".md": MarkdownReader(),
        ".docx": DocxReader(),
        ".txt": FlatReader(),
        ".hwp": HWPReader(),
    }


def parse(kb_id: str, object_key: str, local_path: Path | None = None) -> list[Document]:
    """
    S3에서 파일을 다운로드하고 LlamaIndex Document 리스트로 변환한다.

    Args:
        kb_id: 지식베이스 ID
        object_key: S3 오브젝트 키 (kb_id prefix 제외)
        local_path: 이미 로컬에 있는 파일 경로 (로컬 테스트용)

    Returns:
        LlamaIndex Document 리스트
    """
    suffix = Path(object_key).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise IngestValidationError(f"Unsupported file format: {suffix}")

    with tempfile.TemporaryDirectory() as tmpdir:
        if local_path is None:
            dest = Path(tmpdir) / Path(object_key).name
            download_object(kb_id, object_key, dest)
            file_path = dest
        else:
            file_path = local_path

        extractor = _get_file_extractor()
        reader = SimpleDirectoryReader(
            input_files=[str(file_path)],
            file_extractor=extractor if extractor else None,
        )
        documents = reader.load_data()

        doc_created_at = _extract_doc_created_at(file_path, suffix, kb_id, object_key)

        # 문서 메타데이터 보강
        for doc in documents:
            doc.metadata.update(
                {
                    "kb_id": kb_id,
                    "doc_key": f"{kb_id}/{object_key}",
                    "object_key": object_key,
                    "doc_type": suffix.lstrip("."),
                    "doc_created_at": doc_created_at,
                }
            )

        logger.info(
            "Parsed: kb=%s key=%s documents=%d doc_created_at=%s",
            kb_id, object_key, len(documents), doc_created_at or "n/a",
        )
        return documents


def parse_local(file_path: Path, kb_id: str = "local", object_key: str | None = None) -> list[Document]:
    """로컬 파일을 직접 파싱 (CLI / 테스트용)."""
    key = object_key or file_path.name
    return parse(kb_id=kb_id, object_key=key, local_path=file_path)