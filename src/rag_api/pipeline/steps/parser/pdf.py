"""parser.pdf — PDF reader (moved from parse.py, no behavior change)."""

from __future__ import annotations

from pathlib import Path

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader


class PyMuPDFReader(BaseReader):
    """PDF reader using PyMuPDF (fitz) instead of pypdf.

    Keynote/Pages PDF exports often embed subset CID fonts without a valid
    ToUnicode CMap, so pypdf's glyph-to-unicode mapping (extract_doc.py's
    PDFReader) returns garbled or empty text for CJK content while ASCII
    text extracts fine. PyMuPDF resolves glyphs via the font's own cmap
    table and handles this case correctly.
    """

    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        import fitz

        docs = []
        with fitz.open(str(file)) as pdf:
            for page_num, page in enumerate(pdf, start=1):
                metadata = {
                    "page_num": page_num,
                    "page_label": page.get_label() or None,
                    "file_name": Path(file).name,
                }
                if extra_info:
                    metadata.update(extra_info)
                docs.append(Document(text=page.get_text(), metadata=metadata))
        return docs
