"""chunk Op 단위 테스트."""

from __future__ import annotations

from collections import Counter

import pytest
from llama_index.core import Document

_PARENT_CHILD_TEXT = (
    "하이브리드 검색은 Dense 벡터와 Sparse 벡터를 결합해 검색 정확도를 높이는 방식이다. "
    "Dense 벡터는 의미 기반 유사도를 포착하고, Sparse 벡터는 키워드 일치를 포착한다. "
    "두 점수는 RRF(Reciprocal Rank Fusion)로 통합되어 최종 순위가 결정된다.\n\n"
    "리랭킹은 검색 후보 결과에 대해 정밀한 재순위를 수행하는 단계다. "
    "Jina API 같은 외부 리랭커를 사용하거나, 자체 호스팅한 Cohere 호환 서버를 사용할 수 있다. "
    "리랭커가 비활성화된 경우 RRF 점수를 그대로 최종 순위로 사용한다.\n\n"
    "임베딩은 텍스트를 벡터로 변환하는 과정이다. "
    "Dense 임베딩은 Ollama(bge-m3)나 OpenAI 모델을 사용하고, Sparse 임베딩은 BM25 기반 TF 인코더를 사용한다. "
    "두 벡터는 각각 Qdrant에 저장되어 하이브리드 검색에 활용된다."
)


def test_chunk_recursive_splits_long_text():
    """recursive 전략: 긴 텍스트가 여러 청크로 분할되는지 확인."""
    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text="sample text " * 500)]
    result = chunk(docs, strategy="recursive", chunk_size=128, chunk_overlap=16)

    assert len(result.nodes) > 1
    assert result.parents == []
    assert all(isinstance(n.get_content(), str) for n in result.nodes)


def test_chunk_adds_metadata():
    """청킹 후 메타데이터가 주입되는지 확인."""
    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text="테스트 문서입니다. " * 100)]
    nodes = chunk(docs, strategy="recursive", chunk_size=256, chunk_overlap=32).nodes

    for node in nodes:
        assert "chunk_index" in node.metadata
        assert "total_chunks" in node.metadata
        assert node.metadata["chunk_strategy"] == "recursive"


def test_chunk_single_short_document():
    """짧은 문서는 1개 청크로 반환된다."""
    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text="짧은 텍스트이지만 min_chunk_chars 기준을 충족하는 단일 청크 문서입니다.")]
    nodes = chunk(docs, strategy="recursive", chunk_size=1024, chunk_overlap=128).nodes
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
        nodes_global = chunk(docs, strategy="recursive", chunk_size=1024, chunk_overlap=128).nodes
    assert len(nodes_global) == 1

    with patch(
        "rag_api.infra.postgres.get_kb_settings_overrides",
        return_value={"chunking.min_chunk_chars": 1000},
    ):
        nodes_override = chunk(
            docs, kb_id="kb-01", strategy="recursive", chunk_size=1024, chunk_overlap=128
        ).nodes
    assert len(nodes_override) == 0


def test_chunk_table_content_type_is_not_split():
    """content_type=table 문서는 chunk_size를 넘어도 분할되지 않고 1개 노드로 유지된다."""
    from rag_api.pipeline.steps.chunk import chunk

    long_table_markdown = "| 컬럼 |\n|---|\n" + "\n".join(f"| 행{i} 값입니다 |" for i in range(200))
    docs = [Document(text=long_table_markdown, metadata={"content_type": "table"})]
    nodes = chunk(docs, strategy="recursive", chunk_size=64, chunk_overlap=8).nodes

    assert len(nodes) == 1
    assert nodes[0].get_content() == long_table_markdown
    assert nodes[0].metadata["chunk_strategy"] == "atomic"


def test_chunk_image_caption_content_type_is_not_split():
    """content_type=image_caption 문서도 분할 없이 1개 노드로 유지된다."""
    from rag_api.pipeline.steps.chunk import chunk

    caption = "이미지 캡션 설명 텍스트입니다 " * 50
    docs = [Document(text=caption, metadata={"content_type": "image_caption"})]
    nodes = chunk(docs, strategy="recursive", chunk_size=32, chunk_overlap=4).nodes

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
    nodes = chunk(docs, strategy="recursive", chunk_size=128, chunk_overlap=16).nodes

    content_types = [n.metadata.get("content_type") for n in nodes]
    assert content_types.count("table") == 1
    assert content_types.count("image_caption") == 1
    assert content_types.count("text") >= 1
    # chunk_index/total_chunks assigned across the full merged list
    total = len(nodes)
    assert sorted(n.metadata["chunk_index"] for n in nodes) == list(range(total))
    assert all(n.metadata["total_chunks"] == total for n in nodes)


# ──────────────────────────────────────────────
# hierarchical strategy — docs/internal/design/parent-child-chunking.md
# ──────────────────────────────────────────────

def test_chunk_hierarchical_requires_list_chunk_size():
    """strategy="hierarchical" with a scalar chunk_size fails loudly, not silently."""
    from rag_api.exceptions import ConfigError
    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text=_PARENT_CHILD_TEXT, metadata={"doc_id": "docX"})]
    with pytest.raises(ConfigError):
        chunk(docs, strategy="hierarchical", chunk_size=1024, chunk_overlap=16)


def test_chunk_hierarchical_3level_structure():
    """3-level HierarchicalNodeParser split — leaves + ancestors form a consistent tree."""
    from rag_api.pipeline.steps.chunk import chunk

    doc_id = "a1b2c3d4"
    docs = [Document(text=_PARENT_CHILD_TEXT, metadata={"doc_id": doc_id, "page_num": 1})]
    result = chunk(docs, strategy="hierarchical", chunk_size=[600, 200, 60], chunk_overlap=10)

    assert result.nodes
    assert result.parents

    leaf_ids = {n.node_id for n in result.nodes}
    parent_ids = {p.chunk_id for p in result.parents}

    # every leaf/ancestor ID is deterministic "{doc_id}:{idx}" and globally unique
    assert all(n.node_id.startswith(f"{doc_id}:") for n in result.nodes)
    assert all(p.chunk_id.startswith(f"{doc_id}:") for p in result.parents)
    assert leaf_ids.isdisjoint(parent_ids)

    # every leaf's parent_chunk_id resolves to a stored ancestor
    for n in result.nodes:
        assert n.metadata["parent_chunk_id"] in parent_ids
        assert n.metadata["chunk_strategy"] == "hierarchical"

    # root-first order — required for save_parent_chunks' self-referencing FK insert order
    levels = [p.level for p in result.parents]
    assert levels == sorted(levels)
    roots = [p for p in result.parents if p.parent_id is None]
    assert roots and all(p.level == 0 for p in roots)

    # child_count exactly matches the number of live children (leaves or ancestors) pointing
    # at each ancestor — the core min_chunk_chars-aware calculation in _build_parent_chunks
    leaf_parent_ids = [n.metadata["parent_chunk_id"] for n in result.nodes]
    ancestor_parent_ids = [p.parent_id for p in result.parents if p.parent_id]
    actual_child_counts = Counter(leaf_parent_ids) + Counter(ancestor_parent_ids)
    for p in result.parents:
        assert p.child_count == actual_child_counts[p.chunk_id]
        assert p.child_count > 0  # zero-child ancestors must never be stored


def test_chunk_hierarchical_deterministic_ids_across_calls():
    """Same input -> identical leaf/ancestor IDs (re-ingest replaces the same Postgres rows)."""
    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text=_PARENT_CHILD_TEXT, metadata={"doc_id": "docY"})]
    r1 = chunk(docs, strategy="hierarchical", chunk_size=[600, 200, 60], chunk_overlap=10)
    docs2 = [Document(text=_PARENT_CHILD_TEXT, metadata={"doc_id": "docY"})]
    r2 = chunk(docs2, strategy="hierarchical", chunk_size=[600, 200, 60], chunk_overlap=10)

    assert {n.node_id for n in r1.nodes} == {n.node_id for n in r2.nodes}
    assert {p.chunk_id for p in r1.parents} == {p.chunk_id for p in r2.parents}


def test_chunk_hierarchical_all_leaves_filtered_drops_leaf_parent_ancestors():
    """When min_chunk_chars filters out every leaf, the level immediately above leaves (whose
    child_count would be 0) is never stored (design §4.1, ZeroDivisionError guard in
    rag/retriever.py's auto-merge ratio). Note: in practice this never even reaches upsert() —
    chunk_op/runner.py abort the pipeline on empty result.nodes before parents are persisted —
    so a root row referencing since-dropped children (if any survives here) is dead, unreachable
    data, never looked up by _auto_merge_parents."""
    from unittest.mock import patch

    from rag_api.pipeline.steps.chunk import chunk

    docs = [Document(text=_PARENT_CHILD_TEXT, metadata={"doc_id": "docZ"})]
    with patch(
        "rag_api.infra.postgres.get_kb_settings_overrides",
        return_value={"chunking.min_chunk_chars": 2000},
    ):
        result = chunk(
            docs, kb_id="kb-01", strategy="hierarchical", chunk_size=[600, 200, 60],
            chunk_overlap=10,
        )

    assert result.nodes == []
    assert not any(p.level == 1 for p in result.parents)  # leaf-parent level always dropped
    assert all(p.child_count > 0 for p in result.parents)  # zero-child rows never stored