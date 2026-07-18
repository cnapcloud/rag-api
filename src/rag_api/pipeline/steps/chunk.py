"""chunk Op — LlamaIndex NodeParser chunking (recursive / semantic / code)."""

from __future__ import annotations

import logging
from typing import Literal

from llama_index.core import Document
from llama_index.core.schema import BaseNode

from rag_api.config.settings import get_settings
from rag_api.exceptions import ConfigError
from rag_api.pipeline.steps.parser.extensions import CODE_EXTENSIONS, CODE_LANGUAGE_MAP

logger = logging.getLogger(__name__)

ChunkStrategy = Literal["recursive", "semantic"]

# content_type values whose Document already represents one atomic retrieval unit (a single
# table or a single image caption) -- running these through SentenceSplitter/SemanticSplitter
# has no structural awareness of table rows or caption boundaries and can split them mid-row
# (see rag-ent-api's extract_tables.py / image_ocr.py, the producers of these content_types).
ATOMIC_CONTENT_TYPES = {"table", "image_caption"}


def _build_parser(strategy: ChunkStrategy, chunk_size: int, chunk_overlap: int, semantic_threshold: float):
    if strategy == "recursive":
        from llama_index.core.node_parser import SentenceSplitter

        return SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    elif strategy == "semantic":
        from llama_index.core.node_parser import SemanticSplitterNodeParser

        from rag_api.pipeline.steps.embed import build_embed_model

        embed_model = build_embed_model()
        return SemanticSplitterNodeParser(
            embed_model=embed_model,
            buffer_size=1,
            breakpoint_percentile_threshold=int(semantic_threshold * 100),
        )

    else:
        raise ConfigError(f"Unknown chunking strategy: {strategy}")


def _build_code_parser(language: str, chunk_lines: int, chunk_lines_overlap: int):
    try:
        from llama_index.core.node_parser import CodeSplitter
    except ImportError as e:
        raise ConfigError("CodeSplitter unavailable: install tree-sitter-languages") from e
    return CodeSplitter(language=language, chunk_lines=chunk_lines, chunk_lines_overlap=chunk_lines_overlap)


def _group_by_language(docs: list[Document]) -> list[tuple[str, list[Document]]]:
    groups: dict[str, list[Document]] = {}
    for doc in docs:
        ext = f".{doc.metadata.get('doc_type', '')}"
        lang = CODE_LANGUAGE_MAP.get(ext, "python")
        groups.setdefault(lang, []).append(doc)
    return list(groups.items())


def chunk(
    documents: list[Document],
    strategy: ChunkStrategy | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[BaseNode]:
    """Split documents into nodes, routing code files to CodeSplitter automatically.

    Args:
        documents: LlamaIndex Document list
        strategy: chunking strategy for non-code docs (None -> settings.yaml)
        chunk_size: chunk size override for non-code docs
        chunk_overlap: overlap override for non-code docs

    Returns:
        BaseNode list
    """
    cfg = get_settings().chunking
    _strategy: ChunkStrategy = strategy or cfg.strategy  # type: ignore[assignment]
    _chunk_size = chunk_size or cfg.chunk_size
    _chunk_overlap = chunk_overlap or cfg.chunk_overlap
    _semantic_threshold = cfg.semantic_threshold

    atomic_docs = [d for d in documents if d.metadata.get("content_type") in ATOMIC_CONTENT_TYPES]
    splittable_docs = [d for d in documents if d not in atomic_docs]

    code_docs = [d for d in splittable_docs if f".{d.metadata.get('doc_type', '')}" in CODE_EXTENSIONS]
    text_docs = [d for d in splittable_docs if d not in code_docs]

    nodes: list[BaseNode] = []

    for language, group in _group_by_language(code_docs):
        parser = _build_code_parser(language, cfg.code_chunk_lines, cfg.code_chunk_lines_overlap)
        raw = parser.get_nodes_from_documents(group)
        for n in raw:
            n.metadata["chunk_strategy"] = "code"
        nodes.extend(raw)

    if text_docs:
        parser = _build_parser(_strategy, _chunk_size, _chunk_overlap, _semantic_threshold)
        raw = parser.get_nodes_from_documents(text_docs)
        for n in raw:
            n.metadata.update({"chunk_strategy": _strategy, "chunk_size": _chunk_size, "chunk_overlap": _chunk_overlap})
        nodes.extend(raw)

    for d in atomic_docs:
        d.metadata["chunk_strategy"] = "atomic"
        nodes.append(d)

    nodes = [n for n in nodes if len(n.get_content().strip()) >= cfg.min_chunk_chars]

    for i, node in enumerate(nodes):
        node.metadata.update({"chunk_index": i, "total_chunks": len(nodes)})

    logger.info(
        "Chunking done: code=%d text=%d atomic=%d nodes=%d",
        len(code_docs), len(text_docs), len(atomic_docs), len(nodes),
    )
    return nodes