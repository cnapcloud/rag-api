---
name: hierarchical-node-parser-pitfalls
description: LlamaIndex HierarchicalNodeParser id_func injection and NodeRelationship typing gotchas hit while implementing US-03 (chunking.strategy="hierarchical")
metadata:
  type: project
---

Two non-obvious LlamaIndex internals hit while building `pipeline/steps/chunk.py`'s
`hierarchical` strategy ([[../../../docs/internal/design/parent-child-chunking.md]]).

**id_func injection**: `HierarchicalNodeParser.from_defaults(chunk_sizes=...)` builds its own
`node_parser_map` internally (one `SentenceSplitter` per level) and does NOT expose a way to
pass `id_func` through — so a top-level `id_func=` on the `HierarchicalNodeParser` itself is
silently ignored for node ID generation (IDs stay random UUIDs). To get deterministic
`"{doc_id}:{idx}"` IDs, you must bypass `from_defaults()` and construct `node_parser_map`
manually — one `SentenceSplitter(chunk_size=cs, id_func=id_func)` per level, all sharing the
same closure-scoped counter — then pass `node_parser_map`/`node_parser_ids` directly to
`HierarchicalNodeParser(...)`.

**Why**: Anyone touching `_build_hierarchical_parser` in chunk.py needs this context before
"simplifying" it back to `from_defaults()` — that would silently break re-ingest idempotency
(parent_chunks rows would get new random IDs every ingest instead of being upserted in place).

**NodeRelationship typing**: `node.relationships.get(NodeRelationship.PARENT/CHILD)` is typed
as `RelatedNodeInfo | list[RelatedNodeInfo] | None` regardless of key — PARENT is always a
single `RelatedNodeInfo` and CHILD is always a `list[RelatedNodeInfo]` at runtime, but mypy
can't narrow by key. `chunk.py`'s `_related_id`/`_related_ids` helpers exist purely to isolate
that isinstance-check boilerplate — reuse them instead of re-deriving `.node_id` access inline.

**How to apply**: When touching hierarchical/parent-child chunking code, check this file before
assuming `from_defaults()` or direct `.node_id` access will work as expected.
