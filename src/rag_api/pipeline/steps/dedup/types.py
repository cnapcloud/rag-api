"""Dedup pipeline shared types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BodyMatch = Literal["identical_level", "similar", "none"]
TitleMatch = Literal["same", "changed", "unknown"]


@dataclass
class DedupResult:
    body_match: BodyMatch = "none"
    title_match: TitleMatch = "unknown"
    duplicate_doc_id: str | None = None
    needs_indexing: bool = True
    title_hash: str = ""
    content_simhash: int = 0
    candidate_doc_ids: list[str] = field(default_factory=list)
