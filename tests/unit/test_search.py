"""검색 로직 단위 테스트."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from rag_api.rag.merger import rrf_merge
from rag_api.rag.retriever import SearchResult, search


def _make_result(chunk_id: str, score: float, kb_id: str = "kb-test") -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        kb_id=kb_id,
        doc_key=f"{kb_id}/doc.pdf",
        title="doc.pdf",
        source_type="s3",
        source=f"{kb_id}/doc.pdf",
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


class TestSearchSimilarity:
    def _make_node(self, node_id: str, score: float, metadata: dict | None = None):
        node = MagicMock()
        node.node_id = node_id
        node.score = score
        node.metadata = metadata or {
            "title": "doc.pdf",
            "source_type": "s3",
            "source": "kb-test/doc.pdf",
            "doc_type": "pdf",
            "chunk_index": 0,
            "updated_at": "2025-06-07T00:00:00Z",
        }
        node.get_content.return_value = "text content"
        return node

    def _make_settings(self, top_k: int = 10):
        s = MagicMock()
        s.retrieval.top_k = top_k
        s.retrieval.hybrid.alpha = 0.5
        s.retrieval.rerank.enabled = False
        return s

    def test_uses_dense_only_mode(self):
        mock_index = MagicMock()
        mock_retriever = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever
        mock_retriever.retrieve.return_value = []

        with (
            patch("rag_api.rag.retriever._build_index", return_value=mock_index),
            patch("rag_api.rag.retriever.get_settings", return_value=self._make_settings()),
        ):
            asyncio.run(search("query", ["kb-test"], mode="similarity"))

        call_kwargs = mock_index.as_retriever.call_args.kwargs
        assert call_kwargs["vector_store_query_mode"] == "default"

    def test_min_score_filters_low_results(self):
        nodes = [
            self._make_node("chunk-high", 0.8),
            self._make_node("chunk-low", 0.3),
            self._make_node("chunk-mid", 0.5),
        ]
        mock_index = MagicMock()
        mock_retriever = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever
        mock_retriever.retrieve.return_value = nodes

        with (
            patch("rag_api.rag.retriever._build_index", return_value=mock_index),
            patch("rag_api.rag.retriever.get_settings", return_value=self._make_settings()),
        ):
            results, _, _, _ = asyncio.run(search("query", ["kb-test"], mode="similarity", min_score=0.4))

        assert len(results) == 2
        assert all(r.score >= 0.4 for r in results)
        assert not any(r.chunk_id == "chunk-low" for r in results)

    def test_min_score_zero_returns_all(self):
        nodes = [self._make_node(f"chunk-{i}", 0.1 * i) for i in range(5)]
        mock_index = MagicMock()
        mock_retriever = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever
        mock_retriever.retrieve.return_value = nodes

        with (
            patch("rag_api.rag.retriever._build_index", return_value=mock_index),
            patch("rag_api.rag.retriever.get_settings", return_value=self._make_settings()),
        ):
            results, _, _, _ = asyncio.run(search("query", ["kb-test"], mode="similarity", min_score=0.0))

        assert len(results) == 5

    def test_all_below_threshold_returns_empty(self):
        nodes = [self._make_node("chunk-0", 0.1), self._make_node("chunk-1", 0.2)]
        mock_index = MagicMock()
        mock_retriever = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever
        mock_retriever.retrieve.return_value = nodes

        with (
            patch("rag_api.rag.retriever._build_index", return_value=mock_index),
            patch("rag_api.rag.retriever.get_settings", return_value=self._make_settings()),
        ):
            results, _, _, _ = asyncio.run(search("query", ["kb-test"], mode="similarity", min_score=0.5))

        assert results == []
