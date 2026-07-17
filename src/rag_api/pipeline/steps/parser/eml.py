"""parser.eml — email (.eml) reader using the stdlib email module.

No third-party dependency — RFC 822 message parsing needs nothing beyond stdlib
(mirrors R2R's eml_parser.py, which is likewise dependency-free).
"""

from __future__ import annotations

from email import message_from_bytes, policy
from pathlib import Path

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

_HEADER_FIELDS = ("Subject", "From", "To", "Date")


class EmlReader(BaseReader):
    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        with open(file, "rb") as f:
            raw = f.read()

        message = message_from_bytes(raw, policy=policy.default)

        sections = [
            f"{field}: {message[field]}" for field in _HEADER_FIELDS if message[field]
        ]

        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_content().strip()
                    if body:
                        sections.append(body)
        else:
            body = message.get_content().strip()
            if body:
                sections.append(body)

        metadata: dict = {"file_path": str(file)}
        metadata.update(extra_info or {})

        return [Document(text="\n\n".join(sections), metadata=metadata)]
