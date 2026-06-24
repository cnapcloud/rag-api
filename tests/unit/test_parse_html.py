"""HTMLCleanReader unit tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

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
  <nav>Home | About | Contact</nav>
  <header>Site Header</header>
  <aside>Related links here</aside>
  <main>
    <h1>Main Title</h1>
    <p>This is the main content paragraph.</p>
  </main>
  <footer>Copyright 2025</footer>
  <script>console.log('footer script');</script>
</body>
</html>
"""

HTML_NO_BODY = "<div><p>No body tag content.</p></div>"


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
def html_no_body_file():
    path = _write_html(HTML_NO_BODY)
    yield path
    path.unlink(missing_ok=True)


def test_html_clean_reader_strips_nav_footer_script(html_file):
    from pipeline.ops.parse import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_file)

    assert len(docs) == 1
    text = docs[0].text

    assert "Main Title" in text
    assert "main content paragraph" in text

    assert "Home | About | Contact" not in text
    assert "Site Header" not in text
    assert "Related links here" not in text
    assert "Copyright 2025" not in text
    assert "alert('xss')" not in text
    assert "console.log" not in text
    assert "body { color: red; }" not in text


def test_html_clean_reader_returns_single_document(html_file):
    from pipeline.ops.parse import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_file)

    assert len(docs) == 1
    assert docs[0].text.strip() != ""


def test_html_clean_reader_metadata_contains_file_path(html_file):
    from pipeline.ops.parse import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_file)

    assert docs[0].metadata["file_path"] == str(html_file)


def test_html_clean_reader_extra_info_merged(html_file):
    from pipeline.ops.parse import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_file, extra_info={"doc_id": "abc-123"})

    assert docs[0].metadata["doc_id"] == "abc-123"
    assert docs[0].metadata["file_path"] == str(html_file)


def test_html_clean_reader_no_body_tag(html_no_body_file):
    from pipeline.ops.parse import HTMLCleanReader

    docs = HTMLCleanReader().load_data(html_no_body_file)

    assert len(docs) == 1
    assert "No body tag content." in docs[0].text
