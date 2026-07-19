"""parser.ppt — legacy .ppt (MS PowerPoint 97-2003 binary/OLE) reader via olefile.

Originally shelled out to `catppt` (catdoc apt package), matching the `.doc`/antiword
pattern. Real-file verification (Docker image build + LibreOffice-generated .ppt samples —
see docs/internal/known-issues.md #22) found `catppt` exits 0 but returns empty stdout for
every sample tested, silently dropping all content. Replaced with a pure-Python reader that
opens the OLE "PowerPoint Document" stream directly and scans it for TextBytesAtom/
TextCharsAtom records (type 0x0fa0/0x0fd0) — verified against the same samples that defeated
catppt. This also drops the antiword-style system-binary dependency entirely for this format
(no Dockerfile/apt changes needed for .ppt anymore).

Record layout (MS-PPT binary format): each record has an 8-byte header — 2 bytes
recVer/recInstance, 2 bytes recType, 4 bytes recLen (data length, little-endian) — followed
by recLen bytes of UTF-16-LE text data. The byte sequence matched by _TEXT_RECORD_MARKERS is
the 2-byte recType field, so it sits 2 bytes into the header; data starts 6 bytes after the
marker position (not 8 — an early port of this logic copied a public-domain reference
implementation that sliced from the marker itself instead of the true record start, which
silently dropped the first UTF-16 character of every record).
"""

from __future__ import annotations

import struct
from pathlib import Path

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

from rag_api.exceptions import IngestValidationError

_TEXT_RECORD_MARKERS = (b"\xa0\x0f", b"\xd0\x0f")


class PptReader(BaseReader):
    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        import olefile

        try:
            ole = olefile.OleFileIO(str(file))
        except Exception as e:
            raise IngestValidationError(f"Not a valid OLE file: {file.name}: {e}") from e

        try:
            if not ole.exists("PowerPoint Document"):
                raise IngestValidationError(f"Not a valid PowerPoint file: {file.name}")
            content = ole.openstream("PowerPoint Document").read()
        finally:
            ole.close()

        text = "\n".join(self._extract_text_records(content))

        metadata: dict = {"file_path": str(file)}
        metadata.update(extra_info or {})

        return [Document(text=text, metadata=metadata)]

    @staticmethod
    def _extract_text_records(content: bytes) -> list[str]:
        records: list[str] = []
        pos = 0
        n = len(content)
        while pos < n:
            marker_pos = -1
            for marker in _TEXT_RECORD_MARKERS:
                found = content.find(marker, pos)
                if found != -1 and (marker_pos == -1 or found < marker_pos):
                    marker_pos = found
            if marker_pos == -1 or marker_pos < 2 or marker_pos + 6 > n:
                break

            rec_len = struct.unpack("<I", content[marker_pos + 2 : marker_pos + 6])[0]
            data_start = marker_pos + 6
            data_end = data_start + rec_len
            if data_end > n:
                pos = marker_pos + 1
                continue

            text = content[data_start:data_end].decode("utf-16-le", errors="ignore")
            text = text.rstrip("\x00").strip()
            if text:
                records.append(text)
            pos = data_end
        return records
