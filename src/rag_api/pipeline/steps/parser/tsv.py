"""parser.tsv — TSV reader.

LlamaIndex's CSVReader hardcodes `csv.reader(fp)` with no delimiter override (see
llama_index.readers.file.CSVReader.load_data), so it can't be reused for tab-separated
files as-is — this wraps the same csv module with delimiter="\\t" instead.
"""

from __future__ import annotations

import csv
from pathlib import Path

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader


class TsvReader(BaseReader):
    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        with open(file, encoding="utf-8") as f:
            rows = [", ".join(row) for row in csv.reader(f, delimiter="\t")]

        metadata: dict = {"file_path": str(file)}
        metadata.update(extra_info or {})

        return [Document(text="\n".join(rows), metadata=metadata)]
