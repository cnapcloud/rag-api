"""Unit tests for rag_api.infra.qdrant.ensure_collection error handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from qdrant_client.http.exceptions import UnexpectedResponse

from rag_api.config.settings import get_settings
from rag_api.exceptions import ConfigError
from rag_api.infra.qdrant import ensure_collection


class TestEnsureCollection:
    def test_creates_collection_when_get_collection_returns_404(self, mock_qdrant):
        """A 404 from get_collection means the collection genuinely doesn't exist yet."""
        mock_qdrant.get_collection.side_effect = UnexpectedResponse(
            status_code=404, reason_phrase="Not Found", content=b"{}", headers={}
        )

        ensure_collection("kb-01", mock_qdrant)

        mock_qdrant.create_collection.assert_called_once()

    def test_propagates_non_404_unexpected_response(self, mock_qdrant):
        """A non-404 error (e.g. transient 5xx) must not be treated as 'collection missing'."""
        mock_qdrant.get_collection.side_effect = UnexpectedResponse(
            status_code=500, reason_phrase="Internal Server Error", content=b"{}", headers={}
        )

        with pytest.raises(UnexpectedResponse):
            ensure_collection("kb-01", mock_qdrant)

        mock_qdrant.create_collection.assert_not_called()

    def test_returns_when_collection_matches(self, mock_qdrant):
        vector_size = get_settings().embedding.vector_size
        vectors = {"dense": MagicMock(size=vector_size)}
        mock_qdrant.get_collection.return_value = MagicMock(
            config=MagicMock(params=MagicMock(vectors=vectors))
        )

        ensure_collection("kb-01", mock_qdrant)

        mock_qdrant.create_collection.assert_not_called()

    def test_raises_config_error_on_vector_size_mismatch(self, mock_qdrant):
        vector_size = get_settings().embedding.vector_size
        vectors = {"dense": MagicMock(size=vector_size + 1)}
        mock_qdrant.get_collection.return_value = MagicMock(
            config=MagicMock(params=MagicMock(vectors=vectors))
        )

        with pytest.raises(ConfigError):
            ensure_collection("kb-01", mock_qdrant)
