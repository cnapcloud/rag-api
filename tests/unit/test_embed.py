"""embed Op unit tests."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from llama_index.core.schema import TextNode

from rag_api.config.settings import EmbeddingSettings, ProviderSettings


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
        patch("rag_api.pipeline.steps.embed.build_embed_model", return_value=mock_model),
        patch("rag_api.pipeline.utils.sparse.compute_sparse_tf", side_effect=_sparse_side_effect),
    ):
        from rag_api.pipeline.steps.embed import embed

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
        patch("rag_api.pipeline.steps.embed.build_embed_model", return_value=mock_model),
        patch("rag_api.pipeline.utils.sparse.compute_sparse_tf", side_effect=_sparse_side_effect),
    ):
        from rag_api.pipeline.steps.embed import embed

        nodes = _make_nodes(1)
        result = embed(nodes)

    assert result[0].node.metadata.get("embedding_provider") == "ollama"


# ──────────────────────────────────────────────
# build_embed_model — provider generalization (US-50)
# ──────────────────────────────────────────────

def _patch_settings(monkeypatch, *, name: str, url: str = "", api_key: str = "", model: str = "bge-m3"):
    from rag_api.pipeline.steps import embed as embed_mod

    stub = SimpleNamespace(
        provider=ProviderSettings(name=name, url=url, api_key=api_key),
        embedding=EmbeddingSettings(model=model),
    )
    monkeypatch.setattr(embed_mod, "get_settings", lambda: stub)


def test_build_embed_model_ollama_native_default_url(monkeypatch):
    from llama_index.embeddings.ollama import OllamaEmbedding

    from rag_api.pipeline.steps.embed import build_embed_model

    _patch_settings(monkeypatch, name="ollama")
    m = build_embed_model()

    assert isinstance(m, OllamaEmbedding)
    assert m.base_url == "http://ollama:11434"


def test_build_embed_model_ollama_honours_custom_url(monkeypatch):
    from rag_api.pipeline.steps.embed import build_embed_model

    _patch_settings(monkeypatch, name="ollama", url="http://gpu-box:11434")
    m = build_embed_model()

    assert m.base_url == "http://gpu-box:11434"


def test_build_embed_model_empty_name_falls_back_to_ollama(monkeypatch):
    from llama_index.embeddings.ollama import OllamaEmbedding

    from rag_api.pipeline.steps.embed import build_embed_model

    _patch_settings(monkeypatch, name="")
    m = build_embed_model()

    assert isinstance(m, OllamaEmbedding)
    assert m.base_url == "http://ollama:11434"


def test_build_embed_model_openai_uses_default_endpoint_and_key(monkeypatch):
    from llama_index.embeddings.openai_like import OpenAILikeEmbedding

    from rag_api.pipeline.steps.embed import build_embed_model

    _patch_settings(monkeypatch, name="openai", api_key="sk-abc", model="text-embedding-3-large")
    m = build_embed_model()

    assert isinstance(m, OpenAILikeEmbedding)
    assert m.api_base == "https://api.openai.com/v1"
    assert m.api_key == "sk-abc"
    # unregistered model name passes through (enum validation bypassed)
    assert m.model_name == "text-embedding-3-large"


def test_build_embed_model_unknown_provider_falls_back_to_openai_compatible(monkeypatch, caplog):
    from llama_index.embeddings.openai_like import OpenAILikeEmbedding

    from rag_api.pipeline.steps.embed import build_embed_model

    _patch_settings(monkeypatch, name="vllm", url="http://vllm:8000/v1")
    with caplog.at_level(logging.WARNING, logger="rag_api.pipeline.steps.embed"):
        m = build_embed_model()

    assert isinstance(m, OpenAILikeEmbedding)
    assert m.api_base == "http://vllm:8000/v1"
    assert any("Unrecognized embedding provider" in r.message for r in caplog.records)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_build_embed_model_unknown_provider_injects_placeholder_key(monkeypatch):
    from rag_api.pipeline.steps.embed import build_embed_model

    _patch_settings(monkeypatch, name="vllm", url="http://vllm:8000/v1")  # no api_key
    m = build_embed_model()

    assert m.api_key  # non-empty placeholder so the SDK does not reject it


def test_build_embed_model_unknown_provider_without_url_raises(monkeypatch):
    from rag_api.exceptions import ConfigError
    from rag_api.pipeline.steps.embed import build_embed_model

    _patch_settings(monkeypatch, name="vllm")  # url missing
    with pytest.raises(ConfigError, match="provider.url is required"):
        build_embed_model()


def test_build_embed_model_jina_sends_different_task_for_query_and_passage(monkeypatch):
    from rag_api.pipeline.steps.embed import build_embed_model

    _patch_settings(monkeypatch, name="jina", api_key="jina-key", model="jina-embeddings-v3")
    m = build_embed_model()

    calls: list[dict] = []

    def fake_get_embeddings(**kwargs):
        calls.append(kwargs)
        return [[0.1, 0.2, 0.3]] * len(kwargs["input"])

    m._api.get_embeddings = fake_get_embeddings

    m.get_text_embedding_batch(["passage one", "passage two"])
    m.get_query_embedding("a query")

    passage_call = next(c for c in calls if c["input"] == ["passage one", "passage two"])
    query_call = next(c for c in calls if c["input"] == ["a query"])
    assert passage_call["task"] == "retrieval.passage"
    assert query_call["task"] == "retrieval.query"


def test_build_embed_model_jina_custom_url_overrides_api_endpoint(monkeypatch):
    from rag_api.pipeline.steps.embed import build_embed_model

    _patch_settings(
        monkeypatch, name="jina", url="http://jina-local:8080/v1", api_key="k", model="jina-embeddings-v3"
    )
    m = build_embed_model()

    assert m._api.api_url == "http://jina-local:8080/v1/embeddings"
