"""Unit tests for infra/s3.py upload_object metadata handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.parse import unquote


def test_upload_object_percent_encodes_non_ascii_metadata():
    """Non-ASCII metadata values (e.g. Korean source URLs) must not reach boto3 raw.

    x-amz-meta-* headers must be ASCII — passing raw non-ASCII values raises
    botocore.exceptions.ParamValidationError ("Non ascii characters found in ...").
    """
    from rag_api.infra.s3 import upload_object

    mock_client = MagicMock()
    mock_client.put_object.return_value = {"ETag": '"abc123"'}

    with patch("rag_api.infra.s3.get_s3_client", return_value=mock_client):
        upload_object(
            "kb-01",
            "web/doc-1.html",
            b"<html></html>",
            content_type="text/html",
            metadata={"source-uri": "https://namu.wiki/w/고양이", "doc-id": "doc-1"},
        )

    sent_metadata = mock_client.put_object.call_args.kwargs["Metadata"]
    for value in sent_metadata.values():
        assert value.isascii()
    assert unquote(sent_metadata["source-uri"]) == "https://namu.wiki/w/고양이"
    assert unquote(sent_metadata["doc-id"]) == "doc-1"


def test_upload_object_without_metadata_omits_metadata_kwarg():
    from rag_api.infra.s3 import upload_object

    mock_client = MagicMock()
    mock_client.put_object.return_value = {"ETag": '"abc123"'}

    with patch("rag_api.infra.s3.get_s3_client", return_value=mock_client):
        upload_object("kb-01", "web/doc-1.html", b"<html></html>")

    assert "Metadata" not in mock_client.put_object.call_args.kwargs
