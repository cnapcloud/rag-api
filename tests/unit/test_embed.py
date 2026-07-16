"""embed Op unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from llama_index.core.schema import TextNode


def _make_nodes(n: int = 3) -> list:
    return [TextNode(text=f"chunk {i} " * 50) for i in range(n)]


def _sparse_side_effect(texts):
    n = len(texts)
    return [[0, 1, 2]] * n, [[0.5, 0.3, 0.2]] * n


def test_embed_returns_embedded_nodes():
    """embed returns a list of EmbeddedNode with dense and sparse vectors."""
    mock_model = MagicMock()
    mock_model.get_text_embedding_batch.return_value = [[0.1] * 1024] * 3

    with (
        patch("rag_api.pipeline.step.embed.build_embed_model", return_value=mock_model),
        patch("rag_api.pipeline.utils.sparse.compute_sparse_tf", side_effect=_sparse_side_effect),
    ):
        from rag_api.pipeline.step.embed import embed

        nodes = _make_nodes(3)
        result = embed(nodes)

    assert len(result) == 3
    for en in result:
        assert len(en.dense_vector) == 1024
        assert isinstance(en.sparse_indices, list)
        assert isinstance(en.sparse_values, list)


def test_embed_adds_metadata():
    """embed injects embedding_provider metadata into each node."""
    mock_model = MagicMock()
    mock_model.get_text_embedding_batch.return_value = [[0.0] * 1024]

    with (
        patch("rag_api.pipeline.step.embed.build_embed_model", return_value=mock_model),
        patch("rag_api.pipeline.utils.sparse.compute_sparse_tf", side_effect=_sparse_side_effect),
    ):
        from rag_api.pipeline.step.embed import embed

        nodes = _make_nodes(1)
        result = embed(nodes)

    assert result[0].node.metadata.get("embedding_provider") == "ollama"
