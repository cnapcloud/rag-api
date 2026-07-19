"""Fake parser_plugins entry point used by tests/unit/test_parser_registry.py — exercises the
same "module.path:register" contract a real out-of-repo plugin would use (see
docs/internal/design/parser-registry.md §3)."""

from __future__ import annotations

from pathlib import Path

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

from rag_api.pipeline.steps.parser import register_parser


class FakePdfReader(BaseReader):
    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        return [Document(text="fake pdf")]


def register() -> None:
    register_parser(".fake", FakePdfReader())
    register_parser(".pdf", FakePdfReader())  # exercises "plugin replaces a default"
