"""chunk Op — LlamaIndex NodeParser chunking (recursive / semantic / hierarchical / code)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import count
from typing import Literal

from llama_index.core import Document
from llama_index.core.schema import BaseNode

from rag_api.exceptions import ConfigError
from rag_api.pipeline.steps.parser.extensions import CODE_EXTENSIONS, CODE_LANGUAGE_MAP

logger = logging.getLogger(__name__)

ChunkStrategy = Literal["recursive", "semantic", "hierarchical"]


@dataclass
class ParentChunk:
    """A non-leaf HierarchicalNodeParser node — stored in Postgres, never embedded/searched
    (docs/internal/design/parent-child-chunking.md §4.1)."""

    chunk_id: str
    level: int
    parent_id: str | None
    chunk_index: int
    text: str
    child_count: int
    page_num: int | None
    page_label: str | None


@dataclass
class ChunkResult:
    nodes: list[BaseNode]                        # leaf nodes only — embedding/search target
    parents: list[ParentChunk] = field(default_factory=list)  # empty unless strategy="hierarchical"

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


def _build_code_parser(language: str, max_chars: int):
    try:
        from llama_index.core.node_parser import CodeSplitter
    except ImportError as e:
        raise ConfigError("CodeSplitter unavailable: install tree-sitter-languages") from e
    return CodeSplitter(language=language, max_chars=max_chars)


def _group_by_language(docs: list[Document]) -> list[tuple[str, list[Document]]]:
    groups: dict[str, list[Document]] = {}
    for doc in docs:
        ext = f".{doc.metadata.get('doc_type', '')}"
        lang = CODE_LANGUAGE_MAP.get(ext, "python")
        groups.setdefault(lang, []).append(doc)
    return list(groups.items())


def _make_id_func(doc_id: str):
    """Deterministic "{doc_id}:{idx}" node IDs — one global counter shared across every level of
    a single document's hierarchy (docs/internal/design/parent-child-chunking.md §2). Must be
    set at node-creation time: relationships are built from these IDs, so rewriting IDs after
    the fact would break the parent/child pointers."""
    counter = count()

    def _id_func(i: int, doc: BaseNode) -> str:
        return f"{doc_id}:{next(counter)}"

    return _id_func


def _build_hierarchical_parser(chunk_sizes: list[int], chunk_overlap: int, id_func):
    from llama_index.core.node_parser import HierarchicalNodeParser, NodeParser, SentenceSplitter

    node_parser_ids = [f"level_{i}_size_{cs}" for i, cs in enumerate(chunk_sizes)]
    node_parser_map: dict[str, NodeParser] = {
        node_parser_id: SentenceSplitter(chunk_size=cs, chunk_overlap=chunk_overlap, id_func=id_func)
        for cs, node_parser_id in zip(chunk_sizes, node_parser_ids)
    }
    return HierarchicalNodeParser(
        chunk_sizes=chunk_sizes, node_parser_ids=node_parser_ids, node_parser_map=node_parser_map,
    )


def _related_id(info) -> str | None:
    """RelatedNodeInfo | list[RelatedNodeInfo] | None -> a single node_id. PARENT is always a
    single RelatedNodeInfo by LlamaIndex convention; the list branch exists only because
    `relationships`'s value type is shared with CHILD (always a list)."""
    if info is None:
        return None
    if isinstance(info, list):
        return info[0].node_id if info else None
    return info.node_id


def _related_ids(info) -> list[str]:
    """Same as _related_id but for CHILD, which is always a list."""
    if info is None:
        return []
    if isinstance(info, list):
        return [i.node_id for i in info]
    return [info.node_id]


def _build_parent_chunks(
    ancestor_nodes: list[BaseNode], leaf_ids: set[str], final_nodes: list[BaseNode],
) -> list[ParentChunk]:
    """Convert every non-leaf HierarchicalNodeParser node into a ParentChunk row.

    child_count counts only direct children that survived (leaves: min_chunk_chars filter;
    ancestors: never filtered, always kept) — using the raw relationships[CHILD] length would
    overcount once min_chunk_chars drops some leaves, always understating the true merge ratio
    (design §4.3). Ancestors whose child_count drops to 0 are skipped entirely to keep
    _auto_merge_parents' ratio division safe (design §4.1).
    """
    from llama_index.core.schema import NodeRelationship

    surviving_leaf_ids = {n.node_id for n in final_nodes if n.node_id in leaf_ids}
    ancestor_ids = {n.node_id for n in ancestor_nodes}
    kept_ids = surviving_leaf_ids | ancestor_ids

    by_id = {n.node_id: n for n in ancestor_nodes}
    levels: dict[str, int] = {}

    def _level_of(node: BaseNode) -> int:
        if node.node_id not in levels:
            parent_id = _related_id(node.relationships.get(NodeRelationship.PARENT))
            parent_node = by_id.get(parent_id) if parent_id else None
            levels[node.node_id] = _level_of(parent_node) + 1 if parent_node else 0
        return levels[node.node_id]

    # root-first order — save_parent_chunks() inserts in this order, and the self-referencing
    # parent_id FK requires each row's parent to already exist (design §3.1).
    ordered = sorted(ancestor_nodes, key=_level_of)

    level_counters: dict[int, int] = {}
    parents: list[ParentChunk] = []
    for node in ordered:
        level = levels[node.node_id]
        child_ids = _related_ids(node.relationships.get(NodeRelationship.CHILD))
        child_count = sum(1 for cid in child_ids if cid in kept_ids)
        if child_count == 0:
            continue

        chunk_index = level_counters.get(level, 0)
        level_counters[level] = chunk_index + 1

        parents.append(
            ParentChunk(
                chunk_id=node.node_id,
                level=level,
                parent_id=_related_id(node.relationships.get(NodeRelationship.PARENT)),
                chunk_index=chunk_index,
                text=node.get_content(),
                child_count=child_count,
                page_num=node.metadata.get("page_num"),
                page_label=node.metadata.get("page_label"),
            )
        )
    return parents


def chunk(
    documents: list[Document],
    kb_id: str | None = None,
    strategy: ChunkStrategy | None = None,
    chunk_size: int | list[int] | None = None,
    chunk_overlap: int | None = None,
) -> ChunkResult:
    """Split documents into nodes, routing code files to CodeSplitter automatically.

    Args:
        documents: LlamaIndex Document list
        kb_id: KB the documents belong to — resolves KB-scoped settings overrides
            (docs/internal/design/kb-settings-override.md). None -> global settings only.
        strategy: chunking strategy for non-code docs (None -> resolved settings)
        chunk_size: chunk size override for non-code docs (list -> strategy="hierarchical" only)
        chunk_overlap: overlap override for non-code docs

    Returns:
        ChunkResult(nodes=leaf nodes, parents=ancestor rows — empty unless
        strategy="hierarchical", docs/internal/design/parent-child-chunking.md §4.3)
    """
    from rag_api.config.settings import resolve_settings

    cfg = resolve_settings(kb_id).chunking
    _strategy: ChunkStrategy = strategy or cfg.strategy  # type: ignore[assignment]
    _chunk_size = chunk_size or cfg.chunk_size
    _chunk_overlap = chunk_overlap or cfg.chunk_overlap
    _semantic_threshold = cfg.semantic_threshold

    atomic_docs = [d for d in documents if d.metadata.get("content_type") in ATOMIC_CONTENT_TYPES]
    splittable_docs = [d for d in documents if d not in atomic_docs]

    code_docs = [d for d in splittable_docs if f".{d.metadata.get('doc_type', '')}" in CODE_EXTENSIONS]
    text_docs = [d for d in splittable_docs if d not in code_docs]

    nodes: list[BaseNode] = []
    ancestor_nodes: list[BaseNode] = []
    leaf_ids: set[str] = set()

    for language, group in _group_by_language(code_docs):
        parser = _build_code_parser(language, cfg.code_max_chars)
        raw = parser.get_nodes_from_documents(group)
        for n in raw:
            n.metadata["chunk_strategy"] = "code"
        nodes.extend(raw)

    if text_docs:
        if _strategy == "hierarchical":
            from llama_index.core.node_parser import get_leaf_nodes
            from llama_index.core.schema import NodeRelationship

            if not isinstance(_chunk_size, list):
                raise ConfigError(
                    "chunking.strategy='hierarchical' requires chunk_size to be a list of "
                    f"levels (got {_chunk_size!r})"
                )

            doc_id = text_docs[0].metadata.get("doc_id", "")
            id_func = _make_id_func(doc_id)
            parser = _build_hierarchical_parser(_chunk_size, _chunk_overlap, id_func)
            all_nodes = parser.get_nodes_from_documents(text_docs)

            leaves = get_leaf_nodes(all_nodes)
            leaf_ids = {n.node_id for n in leaves}
            ancestor_nodes = [n for n in all_nodes if n.node_id not in leaf_ids]

            for n in leaves:
                n.metadata.update({
                    "chunk_strategy": "hierarchical",
                    "chunk_size": _chunk_size,
                    "chunk_overlap": _chunk_overlap,
                    "parent_chunk_id": _related_id(n.relationships.get(NodeRelationship.PARENT)),
                })
            nodes.extend(leaves)
        else:
            # strategy != "hierarchical" always resolves chunk_size to a plain int (design §6) —
            # a mismatched KB override (e.g. a list here) fails loudly inside SentenceSplitter
            # instead of silently doing the wrong thing.
            assert isinstance(_chunk_size, int)
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

    parents = _build_parent_chunks(ancestor_nodes, leaf_ids, nodes) if ancestor_nodes else []

    logger.info(
        "Chunking done: code=%d text=%d atomic=%d nodes=%d parents=%d",
        len(code_docs), len(text_docs), len(atomic_docs), len(nodes), len(parents),
    )
    return ChunkResult(nodes=nodes, parents=parents)