"""HTMLCleanReader unit tests (trafilatura density-based extraction)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

HTML_WITH_BOILERPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <title>Test Page</title>
  <style>body { color: red; }</style>
  <script>alert('xss');</script>
</head>
<body>
  <nav><ul><li><a href="/">Home</a></li><li><a href="/about">About</a></li>
  <li><a href="/contact">Contact</a></li></ul></nav>
  <header>Site Header</header>
  <aside><ul><li><a href="/x">Related link one</a></li>
  <li><a href="/y">Related link two</a></li></ul></aside>
  <main>
    <h1>Main Title</h1>
    <p>This is the first paragraph of the main content, describing the topic in
    reasonable detail so that trafilatura recognizes this block as the primary
    content area of the page.</p>
    <h2>Subheading</h2>
    <ul>
      <li>First bullet point item</li>
      <li>Second bullet point item</li>
    </ul>
    <p>This is a second paragraph adding more substantive content to increase
    the text density of the main content block relative to the surrounding
    navigation and boilerplate elements.</p>
  </main>
  <footer>Copyright 2025 Example Corp</footer>
  <script>console.log('footer script');</script>
</body>
</html>
"""

# No visible text anywhere in the document (empty anchor, empty div) -> trafilatura.extract()
# returns None regardless of extraction policy. A nav-with-real-link-text fixture is NOT used here
# because under html_extraction_policy="lenient" trafilatura's "keep at least something" fallback
# can surface short nav link text instead of returning None (see US-39) — this fixture has no
# text at all so the None-result contract holds in every policy.
HTML_ONLY_BOILERPLATE = """\
<html><body>
<nav><ul><li><a href="/"></a></li></ul></nav>
<div id="root"></div>
</body></html>
"""


def _write_html(content: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
    tmp.write(content)
    tmp.flush()
    return Path(tmp.name)


@pytest.fixture
def html_file():
    path = _write_html(HTML_WITH_BOILERPLATE)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def html_only_boilerplate_file():
    path = _write_html(HTML_ONLY_BOILERPLATE)
    yield path
    path.unlink(missing_ok=True)


def test_html_clean_reader_extracts_main_content_excludes_boilerplate(html_file):
    from rag_api.pipeline.step.parser.html import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_file)

    assert len(docs) == 1
    text = docs[0].text

    assert "Main Title" in text
    assert "first paragraph of the main content" in text
    assert "second paragraph adding more substantive content" in text

    assert "Home" not in text
    assert "About" not in text
    assert "Site Header" not in text
    assert "Related link" not in text
    assert "Copyright 2025" not in text
    assert "alert('xss')" not in text
    assert "console.log" not in text
    assert "color: red" not in text


def test_html_clean_reader_preserves_markdown_structure(html_file):
    from rag_api.pipeline.step.parser.html import HTMLCleanReader

    text = HTMLCleanReader().load_data(html_file)[0].text

    assert "# Main Title" in text
    assert "## Subheading" in text
    assert "- First bullet point item" in text
    assert "- Second bullet point item" in text


def test_html_clean_reader_returns_single_document(html_file):
    from rag_api.pipeline.step.parser.html import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_file)

    assert len(docs) == 1
    assert docs[0].text.strip() != ""


def test_html_clean_reader_metadata_contains_file_path(html_file):
    from rag_api.pipeline.step.parser.html import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_file)

    assert docs[0].metadata["file_path"] == str(html_file)


def test_html_clean_reader_extra_info_merged(html_file):
    from rag_api.pipeline.step.parser.html import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_file, extra_info={"doc_id": "abc-123"})

    assert docs[0].metadata["doc_id"] == "abc-123"
    assert docs[0].metadata["file_path"] == str(html_file)


@pytest.mark.parametrize(
    ("policy", "expected_precision", "expected_recall"),
    [
        ("strict", True, False),
        ("lenient", False, True),
        ("balanced", False, False),
    ],
)
def test_html_clean_reader_maps_extraction_policy_to_trafilatura_kwargs(
    html_file, policy, expected_precision, expected_recall
):
    from rag_api.pipeline.step.parser.html import HTMLCleanReader

    with (
        patch("rag_api.config.settings.get_settings") as mock_get_settings,
        patch("trafilatura.extract") as mock_extract,
    ):
        mock_get_settings.return_value.ingestion.html_extraction_policy = policy
        mock_extract.return_value = "stub"

        HTMLCleanReader().load_data(html_file)

        assert mock_extract.call_args.kwargs["favor_precision"] is expected_precision
        assert mock_extract.call_args.kwargs["favor_recall"] is expected_recall


def test_html_clean_reader_no_extractable_content_returns_empty_text(
    html_only_boilerplate_file,
):
    from rag_api.pipeline.step.parser.html import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_only_boilerplate_file)

    assert len(docs) == 1
    assert docs[0].text == ""
    assert docs[0].metadata["file_path"] == str(html_only_boilerplate_file)
