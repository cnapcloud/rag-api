"""parse() integration with the parser_registry — default behavior parity, post-processor
application, and unsupported-format rejection after unregistering a default parser."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from llama_index.core import Document

from rag_api.exceptions import IngestValidationError
from rag_api.pipeline.steps import parser as parser_registry


@pytest.fixture(autouse=True)
def _reset_registry():
    parser_registry.reset_registry()
    yield
    parser_registry.reset_registry()


@pytest.fixture
def txt_file():
    tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8")
    tmp.write("hello world, this is plain text content for parsing.")
    tmp.flush()
    path = Path(tmp.name)
    yield path
    path.unlink(missing_ok=True)


def test_parse_local_default_behavior_unchanged(txt_file):
    from rag_api.pipeline.steps.parse import parse_local

    docs = parse_local(txt_file)

    assert len(docs) == 1
    assert "hello world" in docs[0].text
    assert docs[0].metadata["doc_type"] == "txt"


def test_parse_applies_registered_post_processor(txt_file):
    from rag_api.pipeline.steps.parse import parse_local

    def add_caption(documents: list[Document], file_path: Path, suffix: str, kb_id: str | None) -> list[Document]:
        return [Document(text=f"caption for {file_path.name}", metadata={"type": "image_caption"})]

    parser_registry.register_post_processor(add_caption)

    docs = parse_local(txt_file)

    assert len(docs) == 2
    caption_docs = [d for d in docs if d.metadata.get("type") == "image_caption"]
    assert len(caption_docs) == 1
    assert "caption for" in caption_docs[0].text
    # post-processor-added documents still get the same doc_id/doc_type tagging as the rest
    assert caption_docs[0].metadata["doc_type"] == "txt"


def test_parse_rejects_unregistered_extension(txt_file):
    from rag_api.pipeline.steps.parse import parse_local

    parser_registry.get_parsers()  # trigger default load
    parser_registry.unregister_parser(".txt")

    with pytest.raises(IngestValidationError):
        parse_local(txt_file)
