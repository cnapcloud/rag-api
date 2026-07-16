"""chunk Op 단위 테스트."""

from __future__ import annotations

import pytest
from llama_index.core import Document


def test_chunk_recursive_splits_long_text():
    """recursive 전략: 긴 텍스트가 여러 청크로 분할되는지 확인."""
    from rag_api.pipeline.step.chunk import chunk

    docs = [Document(text="sample text " * 500)]
    nodes = chunk(docs, strategy="recursive", chunk_size=128, chunk_overlap=16)

    assert len(nodes) > 1
    assert all(isinstance(n.get_content(), str) for n in nodes)


def test_chunk_adds_metadata():
    """청킹 후 메타데이터가 주입되는지 확인."""
    from rag_api.pipeline.step.chunk import chunk

    docs = [Document(text="테스트 문서입니다. " * 100)]
    nodes = chunk(docs, strategy="recursive", chunk_size=256, chunk_overlap=32)

    for node in nodes:
        assert "chunk_index" in node.metadata
        assert "total_chunks" in node.metadata
        assert node.metadata["chunk_strategy"] == "recursive"


@pytest.mark.skip(reason="document_aware strategy not yet implemented — pending US-03")
def test_chunk_document_aware_returns_leaf_nodes():
    """document_aware 전략: 리프 노드만 반환되는지 확인."""
    from rag_api.pipeline.step.chunk import chunk

    docs = [Document(text="단락 " * 500)]
    nodes = chunk(docs, strategy="document_aware", chunk_size=512, chunk_overlap=64)
    assert len(nodes) > 0


def test_chunk_single_short_document():
    """짧은 문서는 1개 청크로 반환된다."""
    from rag_api.pipeline.step.chunk import chunk

    docs = [Document(text="짧은 텍스트이지만 min_chunk_chars 기준을 충족하는 단일 청크 문서입니다.")]
    nodes = chunk(docs, strategy="recursive", chunk_size=1024, chunk_overlap=128)
    assert len(nodes) == 1