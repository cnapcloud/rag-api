"""chunk Op 단위 테스트."""

from __future__ import annotations

import pytest
from llama_index.core import Document


def test_chunk_recursive_splits_long_text():
    """recursive 전략: 긴 텍스트가 여러 청크로 분할되는지 확인."""
    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text="sample text " * 500)]
    nodes = chunk(docs, strategy="recursive", chunk_size=128, chunk_overlap=16)

    assert len(nodes) > 1
    assert all(isinstance(n.get_content(), str) for n in nodes)


def test_chunk_adds_metadata():
    """청킹 후 메타데이터가 주입되는지 확인."""
    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text="테스트 문서입니다. " * 100)]
    nodes = chunk(docs, strategy="recursive", chunk_size=256, chunk_overlap=32)

    for node in nodes:
        assert "chunk_index" in node.metadata
        assert "total_chunks" in node.metadata
        assert node.metadata["chunk_strategy"] == "recursive"


@pytest.mark.skip(reason="document_aware strategy not yet implemented — pending US-03")
def test_chunk_document_aware_returns_leaf_nodes():
    """document_aware 전략: 리프 노드만 반환되는지 확인."""
    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text="단락 " * 500)]
    nodes = chunk(docs, strategy="document_aware", chunk_size=512, chunk_overlap=64)
    assert len(nodes) > 0


def test_chunk_single_short_document():
    """짧은 문서는 1개 청크로 반환된다."""
    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text="짧은 텍스트이지만 min_chunk_chars 기준을 충족하는 단일 청크 문서입니다.")]
    nodes = chunk(docs, strategy="recursive", chunk_size=1024, chunk_overlap=128)
    assert len(nodes) == 1


def test_chunk_applies_kb_scoped_min_chunk_chars_override():
    """KB override for chunking.min_chunk_chars actually changes chunk() output end-to-end —
    proves the resolve_settings(kb_id) wiring (docs/internal/design/kb-settings-override.md).
    min_chunk_chars isn't an explicit chunk() parameter (unlike strategy/chunk_size/chunk_overlap),
    so this only passes if kb_id correctly reaches resolve_settings() inside chunk()."""
    from unittest.mock import patch

    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text="word " * 10)]  # 50 chars: clears global default (30), not a KB override of 1000

    with patch("rag_api.infra.postgres.get_kb_settings_overrides", return_value={}):
        nodes_global = chunk(docs, strategy="recursive", chunk_size=1024, chunk_overlap=128)
    assert len(nodes_global) == 1

    with patch(
        "rag_api.infra.postgres.get_kb_settings_overrides",
        return_value={"chunking.min_chunk_chars": 1000},
    ):
        nodes_override = chunk(
            docs, kb_id="kb-01", strategy="recursive", chunk_size=1024, chunk_overlap=128
        )
    assert len(nodes_override) == 0


def test_chunk_table_content_type_is_not_split():
    """content_type=table 문서는 chunk_size를 넘어도 분할되지 않고 1개 노드로 유지된다."""
    from rag_api.pipeline.steps.chunk import chunk

    long_table_markdown = "| 컬럼 |\n|---|\n" + "\n".join(f"| 행{i} 값입니다 |" for i in range(200))
    docs = [Document(text=long_table_markdown, metadata={"content_type": "table"})]
    nodes = chunk(docs, strategy="recursive", chunk_size=64, chunk_overlap=8)

    assert len(nodes) == 1
    assert nodes[0].get_content() == long_table_markdown
    assert nodes[0].metadata["chunk_strategy"] == "atomic"


def test_chunk_image_caption_content_type_is_not_split():
    """content_type=image_caption 문서도 분할 없이 1개 노드로 유지된다."""
    from rag_api.pipeline.steps.chunk import chunk

    caption = "이미지 캡션 설명 텍스트입니다 " * 50
    docs = [Document(text=caption, metadata={"content_type": "image_caption"})]
    nodes = chunk(docs, strategy="recursive", chunk_size=32, chunk_overlap=4)

    assert len(nodes) == 1
    assert nodes[0].get_content() == caption
    assert nodes[0].metadata["chunk_strategy"] == "atomic"


def test_chunk_atomic_docs_mixed_with_text_docs_all_present():
    """일반 text 문서는 분할되고 table/image_caption 문서는 그대로 섞여 최종 노드 리스트에 남는다."""
    from rag_api.pipeline.steps.chunk import chunk

    docs = [
        Document(text="sample text " * 500, metadata={"content_type": "text"}),
        Document(
            text="| 컬럼A | 컬럼B |\n|---|---|\n| 값1 | 값2 |\n| 값3 | 값4 |",
            metadata={"content_type": "table"},
        ),
        Document(
            text="이미지에는 위험등급 안내 아이콘이 표시되어 있으며 3등급 중위험을 의미합니다.",
            metadata={"content_type": "image_caption"},
        ),
    ]
    nodes = chunk(docs, strategy="recursive", chunk_size=128, chunk_overlap=16)

    content_types = [n.metadata.get("content_type") for n in nodes]
    assert content_types.count("table") == 1
    assert content_types.count("image_caption") == 1
    assert content_types.count("text") >= 1
    # chunk_index/total_chunks assigned across the full merged list
    total = len(nodes)
    assert sorted(n.metadata["chunk_index"] for n in nodes) == list(range(total))
    assert all(n.metadata["total_chunks"] == total for n in nodes)