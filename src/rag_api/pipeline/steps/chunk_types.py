"""Dependency-free chunking type aliases.

Kept out of chunk.py (which imports llama_index at module load) so that
rag_api.config.settings can reference ChunkStrategy without pulling the
llama_index import tree onto every importer's path -- notably the Dagster
code server boot (rag_api.defs.definitions).
"""

from __future__ import annotations

from typing import Literal

ChunkStrategy = Literal["recursive", "semantic", "hierarchical"]
