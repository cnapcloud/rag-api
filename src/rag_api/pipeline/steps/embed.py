"""embed Op — LlamaIndex Embedding (Dense + Sparse) asyncio 병렬 처리."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from llama_index.core.schema import BaseNode

from rag_api.config.settings import get_settings, resolve_provider_conn
from rag_api.exceptions import ConfigError

logger = logging.getLogger(__name__)

# SDK가 빈 api_key를 거부하지만 인증 없는 자체 호스팅 서버는 값을 무시한다. 미지 provider가
# api_key 없이 들어오면 이 placeholder를 주입한다.
_OPENAI_COMPAT_PLACEHOLDER_KEY = "sk-no-auth"


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
    """settings.yaml provider에 따라 LlamaIndex Embedding 모델을 반환한다.

    provider는 "프로토콜(name) + 주소(url) + 인증(api_key)"으로 해석된다. `ollama` / `openai` /
    `jina`는 네이티브 클래스를 쓰고, 그 외 미지 name은 에러가 아니라 OpenAI 호환 클라이언트로
    폴백한다 (vLLM, Text Embeddings Inference, Gemini OpenAI 호환 레이어 등).
    docs/internal/design/settings-composition.md provider 절 참고.
    """
    provider = get_settings().provider
    cfg = get_settings().embedding
    name = (provider.name or "").strip()
    conn = resolve_provider_conn(provider)

    if name in ("", "ollama"):
        from llama_index.embeddings.ollama import OllamaEmbedding

        return OllamaEmbedding(model_name=cfg.model, base_url=conn.base_url)

    if name == "jina":
        # 인제스트(passage)와 검색(query) 호출에 서로 다른 task 값이 나가야 query/passage 비대칭이
        # 유지된다 — Jina를 OpenAI 호환이 아니라 네이티브로 두는 이유.
        return _build_jina(model=cfg.model, api_key=conn.api_key or "", base_url=conn.base_url)

    if name == "openai":
        # 모델명 enum 검증을 우회해 최신/미등록 모델명도 그대로 통과시킨다 (OpenAILikeEmbedding).
        # url이 비면 OpenAI 기본 엔드포인트.
        return _build_openai_like(
            model=cfg.model,
            api_base=conn.base_url or "https://api.openai.com/v1",
            api_key=conn.api_key or "",
        )

    # 미지 name → OpenAI 호환 폴백. 에러가 아니지만 오타(`ollamaa`)가 조용히 404로 새는 것을
    # 막기 위해 WARNING 흔적을 남긴다.
    logger.warning(
        "Unrecognized embedding provider %r; falling back to OpenAI-compatible client (url=%s)",
        provider.name,
        conn.base_url,
    )
    if not conn.base_url:
        raise ConfigError(
            f"provider.url is required for OpenAI-compatible provider {provider.name!r} "
            "(must be a full base URL including /v1)"
        )
    return _build_openai_like(
        model=cfg.model,
        api_base=conn.base_url,
        api_key=conn.api_key or _OPENAI_COMPAT_PLACEHOLDER_KEY,
    )


def _build_openai_like(model: str, api_base: str, api_key: str):
    """OpenAI 호환 임베딩 클라이언트. model enum 검증을 우회하고 커스텀 base_url을 받는다."""
    from llama_index.embeddings.openai_like import OpenAILikeEmbedding

    return OpenAILikeEmbedding(model_name=model, api_base=api_base, api_key=api_key)


def _build_jina(model: str, api_key: str, base_url: str | None):
    """Jina 네이티브 임베딩. 방향별로 task를 고정한다 — llama-index-embeddings-jinaai는 task를
    방향과 무관하게 단일 값으로 보내므로, 인제스트는 retrieval.passage / 검색은 retrieval.query가
    나가도록 서브클래스로 강제한다."""
    from llama_index.embeddings.jinaai import JinaEmbedding

    class _AsymmetricJinaEmbedding(JinaEmbedding):
        _QUERY_TASK = "retrieval.query"
        _PASSAGE_TASK = "retrieval.passage"

        def _get_query_embedding(self, query: str) -> list[float]:
            return self._api.get_embeddings(
                input=[query],
                encoding_type=self._encoding_queries,
                task=self._QUERY_TASK,
                dimensions=self._dimensions,
                late_chunking=self._late_chunking,
            )[0]

        async def _aget_query_embedding(self, query: str) -> list[float]:
            result = await self._api.aget_embeddings(
                input=[query],
                encoding_type=self._encoding_queries,
                task=self._QUERY_TASK,
                dimensions=self._dimensions,
                late_chunking=self._late_chunking,
            )
            return result[0]

        def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
            return self._api.get_embeddings(
                input=texts,
                encoding_type=self._encoding_documents,
                task=self._PASSAGE_TASK,
                dimensions=self._dimensions,
                late_chunking=self._late_chunking,
            )

        async def _aget_text_embeddings(self, texts: list[str]) -> list[list[float]]:
            return await self._api.aget_embeddings(
                input=texts,
                encoding_type=self._encoding_documents,
                task=self._PASSAGE_TASK,
                dimensions=self._dimensions,
                late_chunking=self._late_chunking,
            )

    emb = _AsymmetricJinaEmbedding(model=model, api_key=api_key)
    if base_url:
        emb._api.api_url = f"{base_url.rstrip('/')}/embeddings"
    return emb


# ──────────────────────────────────────────────
# 배치 임베딩 (asyncio 병렬)
# ──────────────────────────────────────────────

async def _embed_batch_async(
    texts: list[str],
    embed_model,
    batch_size: int = 32,
) -> list[tuple[list[float], list[int], list[float]]]:
    """Dense + Sparse 벡터를 asyncio.gather로 병렬 생성한다."""
    from rag_api.pipeline.utils.sparse import compute_sparse_tf

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
    provider = get_settings().provider
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
        node.metadata["embedding_model"] = cfg.model
        node.metadata["embedding_provider"] = provider.name
        embedded.append(
            EmbeddedNode(
                node=node,
                dense_vector=dense,
                sparse_indices=sp_idx,
                sparse_values=sp_val,
            )
        )

    logger.info("Embedding done: nodes=%d provider=%s model=%s", len(nodes), provider.name, cfg.model)
    return embedded