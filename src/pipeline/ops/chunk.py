"""chunk Op — LlamaIndex NodeParser 청킹 (recursive / semantic)."""

from __future__ import annotations

import logging
from typing import Literal

from llama_index.core import Document
from llama_index.core.schema import BaseNode

from config.settings import get_settings
from exceptions import ConfigError

logger = logging.getLogger(__name__)

ChunkStrategy = Literal["recursive", "semantic"]


def _build_parser(strategy: ChunkStrategy, chunk_size: int, chunk_overlap: int, semantic_threshold: float):
    if strategy == "recursive":
        from llama_index.core.node_parser import SentenceSplitter

        return SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    elif strategy == "semantic":
        from llama_index.core.node_parser import SemanticSplitterNodeParser

        # SemanticSplitter는 embed_model이 필요 — settings에서 가져옴
        from pipeline.ops.embed import build_embed_model

        embed_model = build_embed_model()
        return SemanticSplitterNodeParser(
            embed_model=embed_model,
            buffer_size=1,
            breakpoint_percentile_threshold=int(semantic_threshold * 100),
        )

    else:
        raise ConfigError(f"Unknown chunking strategy: {strategy}")


def chunk(
    documents: list[Document],
    strategy: ChunkStrategy | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[BaseNode]:
    """
    Document 리스트를 Node 리스트로 청킹한다.

    Args:
        documents: LlamaIndex Document 리스트
        strategy: 청킹 전략 (None이면 settings.yaml에서 읽음)
        chunk_size: 청크 크기 (None이면 settings)
        chunk_overlap: 오버랩 크기 (None이면 settings)

    Returns:
        BaseNode 리스트
    """
    cfg = get_settings().chunking
    _strategy: ChunkStrategy = strategy or cfg.strategy  # type: ignore[assignment]
    _chunk_size = chunk_size or cfg.chunk_size
    _chunk_overlap = chunk_overlap or cfg.chunk_overlap
    _semantic_threshold = cfg.semantic_threshold

    parser = _build_parser(_strategy, _chunk_size, _chunk_overlap, _semantic_threshold)

    nodes = parser.get_nodes_from_documents(documents)

    # 각 노드에 청킹 메타데이터 추가
    for i, node in enumerate(nodes):
        node.metadata.update(
            {
                "chunk_index": i,
                "total_chunks": len(nodes),
                "chunk_strategy": _strategy,
                "chunk_size": _chunk_size,
                "chunk_overlap": _chunk_overlap,
            }
        )

    logger.info("Chunking done: strategy=%s nodes=%d", _strategy, len(nodes))
    return nodes