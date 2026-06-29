"""embed Op — LlamaIndex Embedding (Dense + Sparse) asyncio 병렬 처리."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from llama_index.core.schema import BaseNode

from config.settings import get_settings
from exceptions import ConfigError

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 임베딩 결과 타입
# ──────────────────────────────────────────────

@dataclass
class EmbeddedNode:
    node: BaseNode
    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]


# ──────────────────────────────────────────────
# 임베딩 모델 팩토리
# ──────────────────────────────────────────────

def build_embed_model():
    """settings.yaml provider에 따라 LlamaIndex Embedding 모델을 반환한다."""
    cfg = get_settings().embedding

    if cfg.provider == "ollama":
        from llama_index.embeddings.ollama import OllamaEmbedding

        return OllamaEmbedding(
            model_name=cfg.model,
            base_url=cfg.ollama_url,
        )
    elif cfg.provider == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding

        return OpenAIEmbedding(
            model=cfg.openai_model,
            api_key=cfg.openai_api_key,
        )
    else:
        raise ConfigError(f"Unknown embedding provider: {cfg.provider}")


# ──────────────────────────────────────────────
# 배치 임베딩 (asyncio 병렬)
# ──────────────────────────────────────────────

async def _embed_batch_async(
    texts: list[str],
    embed_model,
    batch_size: int = 32,
) -> list[tuple[list[float], list[int], list[float]]]:
    """Dense + Sparse 벡터를 asyncio.gather로 병렬 생성한다."""
    from pipeline.utils.sparse import compute_sparse_tf

    async def embed_dense_batch(batch: list[str]) -> list[list[float]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, embed_model.get_text_embedding_batch, batch)

    async def embed_sparse_batch(batch: list[str]) -> list[tuple[list[int], list[float]]]:
        all_indices, all_values = compute_sparse_tf(batch)
        return list(zip(all_indices, all_values))

    results: list[tuple[list[float], list[int], list[float]]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        dense_vecs, sparse_vecs = await asyncio.gather(
            embed_dense_batch(batch),
            embed_sparse_batch(batch),
        )
        for dense, (sp_idx, sp_val) in zip(dense_vecs, sparse_vecs):
            results.append((dense, sp_idx, sp_val))

    return results


def embed(nodes: list[BaseNode], batch_size: int = 32) -> list[EmbeddedNode]:
    """Node 리스트에 Dense + Sparse 벡터를 주입한다."""
    cfg = get_settings().embedding

    embed_model = build_embed_model()
    texts = [node.get_content() for node in nodes]

    loop = asyncio.new_event_loop()
    try:
        vector_tuples = loop.run_until_complete(
            _embed_batch_async(texts, embed_model, batch_size)
        )
    finally:
        loop.close()

    embedded: list[EmbeddedNode] = []
    for node, (dense, sp_idx, sp_val) in zip(nodes, vector_tuples):
        node.metadata["embedding_model"] = cfg.openai_model if cfg.provider == "openai" else cfg.model
        node.metadata["embedding_provider"] = cfg.provider
        embedded.append(
            EmbeddedNode(
                node=node,
                dense_vector=dense,
                sparse_indices=sp_idx,
                sparse_values=sp_val,
            )
        )

    logger.info("Embedding done: nodes=%d provider=%s model=%s", len(nodes), cfg.provider, cfg.model)
    return embedded