"""parser.doc — legacy .doc (MS Word 97-2003 binary/OLE) reader via antiword.

python-docx only reads the OOXML .docx container; no pure-Python library parses the legacy
binary .doc format, so this shells out to the antiword CLI (apt package `antiword`, installed
in Dockerfile).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

from rag_api.exceptions import ConfigError, IngestValidationError


class DocReader(BaseReader):
    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        try:
            result = subprocess.run(["antiword", str(file)], capture_output=True, check=False)
        except FileNotFoundError as e:
            raise ConfigError(
                "antiword binary not found — install the antiword system package"
            ) from e

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise IngestValidationError(f"antiword failed to parse .doc file: {stderr}")

        text = result.stdout.decode("utf-8", errors="replace")

        metadata: dict = {"file_path": str(file)}
        metadata.update(extra_info or {})

        return [Document(text=text, metadata=metadata)]
