"""embed Op 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from llama_index.core import Document
from llama_index.core.schema import TextNode


def _make_nodes(n: int = 3) -> list:
    return [TextNode(text=f"청크 {i} " * 50) for i in range(n)]


def test_embed_returns_embedded_nodes():
    """embed 함수가 EmbeddedNode 리스트를 반환하는지 확인."""
    mock_model = MagicMock()
    mock_model.get_text_embedding_batch.return_value = [[0.1] * 1024] * 3

    mock_sparse = MagicMock()
    mock_sparse_result = MagicMock()
    mock_sparse_result.indices.tolist.return_value = [0, 1, 2]
    mock_sparse_result.values.tolist.return_value = [0.5, 0.3, 0.2]
    mock_sparse.embed.return_value = iter([mock_sparse_result] * 3)

    with (
        patch("pipeline.ops.embed.build_embed_model", return_value=mock_model),
        patch("pipeline.ops.embed.build_sparse_model", return_value=mock_sparse),
    ):
        from pipeline.ops.embed import embed

        nodes = _make_nodes(3)
        result = embed(nodes)

    assert len(result) == 3
    for en in result:
        assert len(en.dense_vector) == 1024
        assert isinstance(en.sparse_indices, list)
        assert isinstance(en.sparse_values, list)


def test_embed_adds_metadata():
    """임베딩 후 메타데이터가 주입되는지 확인."""
    mock_model = MagicMock()
    mock_model.get_text_embedding_batch.return_value = [[0.0] * 1024]

    with (
        patch("pipeline.ops.embed.build_embed_model", return_value=mock_model),
        patch("pipeline.ops.embed.build_sparse_model", return_value=None),
    ):
        from pipeline.ops.embed import embed

        nodes = _make_nodes(1)
        result = embed(nodes)

    assert result[0].node.metadata.get("embedding_provider") == "ollama"