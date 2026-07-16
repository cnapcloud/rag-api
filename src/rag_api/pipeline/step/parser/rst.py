"""parser.rst — reStructuredText reader using docutils.

The plain FlatReader this replaces returns raw RST source, so directive/markup noise
(`.. code-block::`, `====` section underlines, `:param:` field lists) ends up verbatim in
chunk text. docutils renders RST to an HTML *body fragment* (publish_parts, not
publish_string) so the output has no embedded stylesheet/head to strip — a full-document
render (as R2R's rst_parser.py does with publish_string) pulls in docutils' default CSS as
inline <style> text that tag-stripping alone doesn't remove.
"""

from __future__ import annotations

import html as html_lib
import re
from pathlib import Path

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class RstReader(BaseReader):
    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        from docutils.core import publish_parts
        from docutils.writers import html5_polyglot

        with open(file, encoding="utf-8") as f:
            rst = f.read()

        parts = publish_parts(
            source=rst,
            writer=html5_polyglot.Writer(),
            settings_overrides={"report_level": 5},
        )
        title = parts.get("title", "")
        body = parts.get("body", "")
        html = f"<h1>{title}</h1>{body}" if title else body

        text = _TAG_RE.sub(" ", html)
        text = html_lib.unescape(text)
        text = _WHITESPACE_RE.sub(" ", text).strip()

        metadata: dict = {"file_path": str(file)}
        metadata.update(extra_info or {})

        return [Document(text=text, metadata=metadata)]
