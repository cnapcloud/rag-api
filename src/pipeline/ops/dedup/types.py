"""Dedup pipeline shared types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

DedupVerdict = Literal["identical", "title_changed", "proceed"]


@dataclass
class DedupResult:
    verdict: DedupVerdict
    duplicate_doc_id: str | None = None
    needs_indexing: bool = True
    title_hash: str = ""
    content_simhash: int = 0
    candidate_doc_ids: list[str] = field(default_factory=list)
