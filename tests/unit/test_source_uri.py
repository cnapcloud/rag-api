"""Unit tests for pipeline/utils/source_uri.py."""

from __future__ import annotations

import unicodedata

from rag_api.pipeline.utils.source_uri import normalize_source_uri

# NFC-composed vs percent-encoded forms of the same Hangul path segment (namu.wiki/w/고양이).
_RAW_HANGUL = "https://namu.wiki/w/고양이"
_PERCENT_ENCODED = "https://namu.wiki/w/%EA%B3%A0%EC%96%91%EC%9D%B4"
_NFD_HANGUL = unicodedata.normalize("NFD", _RAW_HANGUL)  # decomposed jamo, same rendered glyphs


def test_web_forces_https_and_lowercases_host():
    assert normalize_source_uri("web", "http://Example.com/Path") == "https://example.com/Path"


def test_web_strips_trailing_slash():
    assert normalize_source_uri("web", "https://example.com/docs/") == "https://example.com/docs"


def test_web_root_path_kept_as_slash():
    assert normalize_source_uri("web", "https://example.com") == "https://example.com/"


def test_web_strips_fragment():
    assert normalize_source_uri("web", "https://example.com/docs#section") == "https://example.com/docs"


def test_web_removes_tracking_params_and_sorts_remaining():
    raw = "https://example.com/docs?utm_source=x&b=2&a=1"
    assert normalize_source_uri("web", raw) == "https://example.com/docs?a=1&b=2"


def test_web_percent_encoded_and_raw_hangul_path_converge():
    """Same page linked once via admin-typed raw URL and once via a crawled
    percent-encoded <a href> must normalize identically, or UNIQUE(kb_id, source)
    fails to catch the duplicate and two documents get created for one page."""
    assert normalize_source_uri("web", _RAW_HANGUL) == normalize_source_uri("web", _PERCENT_ENCODED)


def test_web_nfc_and_nfd_hangul_converge():
    assert normalize_source_uri("web", _RAW_HANGUL) == normalize_source_uri("web", _NFD_HANGUL)


def test_confluence_uses_same_normalization_as_web():
    assert normalize_source_uri("confluence", _PERCENT_ENCODED) == normalize_source_uri("web", _RAW_HANGUL)


def test_github_lowercases_owner_and_repo_only():
    raw = "https://github.com/My-Org/My-Repo/blob/main/src/Main.py"
    assert normalize_source_uri("github", raw) == "https://github.com/my-org/my-repo/blob/main/src/Main.py"


def test_s3_passthrough_unchanged():
    assert normalize_source_uri("s3", "some/key.pdf") == "some/key.pdf"
