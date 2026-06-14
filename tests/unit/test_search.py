"""검색 로직 단위 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rag.merger import rrf_merge
from rag.retriever import SearchResult


def _make_result(chunk_id: str, score: float, kb_id: str = "kb-test") -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_key=f"{kb_id}/doc.pdf",
        doc_type="pdf",
        chunk_index=0,
        page_num=None,
        text="테스트 텍스트",
        score=score,
        rerank_score=None,
        updated_at="2025-06-07T00:00:00Z",
    )


class TestRRFMerge:
    def test_single_list(self):
        results = [_make_result(f"chunk-{i}", 1.0 - i * 0.1) for i in range(5)]
        merged = rrf_merge([results])
        assert len(merged) == 5
        # 순서 유지 확인
        assert merged[0].chunk_id == "chunk-0"

    def test_deduplication(self):
        """동일 chunk_id는 중복 제거되고 RRF 점수가 합산된다."""
        list1 = [_make_result("chunk-A", 0.9), _make_result("chunk-B", 0.8)]
        list2 = [_make_result("chunk-A", 0.7), _make_result("chunk-C", 0.6)]
        merged = rrf_merge([list1, list2])

        ids = [r.chunk_id for r in merged]
        assert ids.count("chunk-A") == 1
        # chunk-A가 두 리스트 모두에 있어 RRF 점수가 더 높아야 함
        chunk_a = next(r for r in merged if r.chunk_id == "chunk-A")
        chunk_b = next(r for r in merged if r.chunk_id == "chunk-B")
        assert chunk_a.score > chunk_b.score

    def test_empty_lists(self):
        merged = rrf_merge([[], []])
        assert merged == []

    def test_multiple_kbs(self):
        kb1 = [_make_result(f"k1-{i}", 1.0 - i * 0.1, "kb1") for i in range(3)]
        kb2 = [_make_result(f"k2-{i}", 1.0 - i * 0.1, "kb2") for i in range(3)]
        merged = rrf_merge([kb1, kb2])
        assert len(merged) == 6