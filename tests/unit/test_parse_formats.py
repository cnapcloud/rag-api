"""New format readers added in US-42/US-43: RstReader/EmlReader/TsvReader/DocReader/PptReader
(custom BaseReader subclasses under pipeline/step/parser/) plus registry-level sanity checks
for the LlamaIndex built-in readers registered for .csv/.json/.epub/.xlsx/.xls/.pptx."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from rag_api.exceptions import ConfigError, IngestValidationError
from rag_api.pipeline.step import parser as parser_registry

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _reset_registry():
    parser_registry.reset_registry()
    yield
    parser_registry.reset_registry()


def _write(suffix: str, content: str | bytes) -> Path:
    if isinstance(content, bytes):
        tmp_bytes = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="wb")
        tmp_bytes.write(content)
        tmp_bytes.flush()
        return Path(tmp_bytes.name)

    tmp_text = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w", encoding="utf-8")
    tmp_text.write(content)
    tmp_text.flush()
    return Path(tmp_text.name)


# ──────────────────────────────────────────────
# RstReader — docutils-based, replaces raw FlatReader
# ──────────────────────────────────────────────

RST_SAMPLE = """\
Title
=====

Some intro text with **bold** content.

.. code-block:: python

   print("hello")

Section
-------

- item one
- item two
"""


class TestRstReader:
    def test_strips_rst_markup(self):
        from rag_api.pipeline.step.parser.rst import RstReader

        path = _write(".rst", RST_SAMPLE)
        try:
            text = RstReader().load_data(path)[0].text
        finally:
            path.unlink(missing_ok=True)

        assert "====" not in text
        assert "-------" not in text
        assert ".. code-block::" not in text

    def test_keeps_prose_content(self):
        from rag_api.pipeline.step.parser.rst import RstReader

        path = _write(".rst", RST_SAMPLE)
        try:
            text = RstReader().load_data(path)[0].text
        finally:
            path.unlink(missing_ok=True)

        assert "Title" in text
        assert "Some intro text with" in text
        assert "bold" in text
        assert "item one" in text
        assert "item two" in text
        assert 'print' in text and "hello" in text

    def test_no_leftover_css_from_html5_writer(self):
        """publish_parts()['body'] must be used instead of a full publish_string() document —
        otherwise docutils' default stylesheet ends up embedded as inline <style> text that
        tag-stripping alone doesn't remove."""
        from rag_api.pipeline.step.parser.rst import RstReader

        path = _write(".rst", RST_SAMPLE)
        try:
            text = RstReader().load_data(path)[0].text
        finally:
            path.unlink(missing_ok=True)

        assert "font-family" not in text
        assert "margin" not in text

    def test_registered_as_default_for_rst(self):
        parsers = parser_registry.get_parsers()
        from rag_api.pipeline.step.parser.rst import RstReader

        assert isinstance(parsers[".rst"], RstReader)


# ──────────────────────────────────────────────
# EmlReader — stdlib email module
# ──────────────────────────────────────────────

EML_SAMPLE = (
    b"Subject: Test Subject\r\n"
    b"From: alice@example.com\r\n"
    b"To: bob@example.com\r\n"
    b"Date: Mon, 1 Jan 2024 10:00:00 +0000\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"This is the email body.\r\n"
)


class TestEmlReader:
    def test_extracts_headers_and_body(self):
        from rag_api.pipeline.step.parser.eml import EmlReader

        path = _write(".eml", EML_SAMPLE)
        try:
            text = EmlReader().load_data(path)[0].text
        finally:
            path.unlink(missing_ok=True)

        assert "Subject: Test Subject" in text
        assert "From: alice@example.com" in text
        assert "To: bob@example.com" in text
        assert "This is the email body." in text

    def test_registered_as_default_for_eml(self):
        parsers = parser_registry.get_parsers()
        assert ".eml" in parsers


# ──────────────────────────────────────────────
# TsvReader — csv module with delimiter="\t"
# ──────────────────────────────────────────────

class TestTsvReader:
    def test_splits_on_tab_not_comma(self):
        from rag_api.pipeline.step.parser.tsv import TsvReader

        path = _write(".tsv", "name\tcity\nAlice, Inc\tSeoul\n")
        try:
            text = TsvReader().load_data(path)[0].text
        finally:
            path.unlink(missing_ok=True)

        assert "Alice, Inc, Seoul" in text

    def test_registered_as_default_for_tsv(self):
        parsers = parser_registry.get_parsers()
        assert ".tsv" in parsers


# ──────────────────────────────────────────────
# CSV/JSON/EPUB/XLSX/XLS — LlamaIndex built-in readers, registered not authored here.
# Sanity check only: the registry wiring in _register_defaults() actually parses each format
# end-to-end via parse_local().
# ──────────────────────────────────────────────

class TestBuiltinFormatRegistration:
    def test_csv_parses(self):
        from rag_api.pipeline.step.parse import parse_local

        path = _write(".csv", "name,city\nAlice,Seoul\n")
        try:
            docs = parse_local(path)
        finally:
            path.unlink(missing_ok=True)

        assert "Alice" in docs[0].text
        assert "Seoul" in docs[0].text

    def test_json_parses(self):
        from rag_api.pipeline.step.parse import parse_local

        path = _write(".json", json.dumps({"name": "Alice", "city": "Seoul"}))
        try:
            docs = parse_local(path)
        finally:
            path.unlink(missing_ok=True)

        assert "Alice" in docs[0].text
        assert "Seoul" in docs[0].text

    def test_epub_parses(self):
        from ebooklib import epub

        from rag_api.pipeline.step.parse import parse_local

        book = epub.EpubBook()
        book.set_identifier("id1")
        book.set_title("Test Book")
        book.set_language("en")
        chapter = epub.EpubHtml(title="Chapter 1", file_name="chap1.xhtml", lang="en")
        chapter.content = "<h1>Chapter 1</h1><p>Hello epub world.</p>"
        book.add_item(chapter)
        book.toc = (epub.Link("chap1.xhtml", "Chapter 1", "chap1"),)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ["nav", chapter]

        path = Path(tempfile.mktemp(suffix=".epub"))
        try:
            epub.write_epub(str(path), book)
            docs = parse_local(path)
        finally:
            path.unlink(missing_ok=True)

        assert any("Hello epub world" in d.text for d in docs)

    def test_xlsx_parses(self):
        import openpyxl

        from rag_api.pipeline.step.parse import parse_local

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["name", "city"])
        ws.append(["Alice", "Seoul"])

        path = Path(tempfile.mktemp(suffix=".xlsx"))
        try:
            wb.save(path)
            docs = parse_local(path)
        finally:
            path.unlink(missing_ok=True)

        assert "Alice" in docs[0].text
        assert "Seoul" in docs[0].text

    def test_xls_parses(self):
        """Legacy .xls fixture — generated once via xlwt (not a project dependency, only used
        offline to produce this binary fixture) and checked in as fixtures/sample.xls."""
        from rag_api.pipeline.step.parse import parse_local

        docs = parse_local(FIXTURES_DIR / "sample.xls")

        assert "Alice" in docs[0].text
        assert "Seoul" in docs[0].text

    def test_pptx_parses(self):
        """.pptx is pure OOXML (python-pptx) — tested end-to-end like the other new-in-US-42
        formats, unlike .doc/.ppt below which need a real antiword/catdoc binary."""
        from pptx import Presentation

        from rag_api.pipeline.step.parse import parse_local

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Hello Slide"
        slide.placeholders[1].text = "Body content here."

        path = Path(tempfile.mktemp(suffix=".pptx"))
        try:
            prs.save(path)
            docs = parse_local(path)
        finally:
            path.unlink(missing_ok=True)

        assert any("Hello Slide" in d.text for d in docs)
        assert any("Body content here" in d.text for d in docs)


# ──────────────────────────────────────────────
# DocReader — legacy .doc via antiword subprocess (US-43)
# ──────────────────────────────────────────────

def _mock_completed_process(returncode: int, stdout: bytes = b"", stderr: bytes = b""):
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


class TestDocReader:
    def test_extracts_text_on_success(self):
        from rag_api.pipeline.step.parser.doc import DocReader

        with patch("subprocess.run", return_value=_mock_completed_process(0, stdout=b"Hello from doc")):
            docs = DocReader().load_data(Path("/fake/path.doc"))

        assert docs[0].text == "Hello from doc"

    def test_calls_antiword_with_file_path(self):
        from rag_api.pipeline.step.parser.doc import DocReader

        with patch("subprocess.run", return_value=_mock_completed_process(0)) as mock_run:
            DocReader().load_data(Path("/fake/path.doc"))

        assert mock_run.call_args.args[0] == ["antiword", "/fake/path.doc"]

    def test_nonzero_exit_raises_ingest_validation_error(self):
        from rag_api.pipeline.step.parser.doc import DocReader

        with patch("subprocess.run", return_value=_mock_completed_process(1, stderr=b"bad format")):
            with pytest.raises(IngestValidationError):
                DocReader().load_data(Path("/fake/path.doc"))

    def test_missing_binary_raises_config_error(self):
        from rag_api.pipeline.step.parser.doc import DocReader

        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(ConfigError):
                DocReader().load_data(Path("/fake/path.doc"))

    def test_registered_as_default_for_doc(self):
        parsers = parser_registry.get_parsers()
        from rag_api.pipeline.step.parser.doc import DocReader

        assert isinstance(parsers[".doc"], DocReader)


# ──────────────────────────────────────────────
# PptReader — legacy .ppt via olefile (US-43, revised)
#
# The original catppt-subprocess implementation had only mock-based tests and shipped with
# a real bug: catppt exits 0 but returns empty stdout for every real .ppt sample tested
# (verified via an actual Docker build — see docs/internal/known-issues.md #22), silently
# dropping all content. These tests use a real fixture instead of mocking the extraction
# mechanism, specifically to avoid repeating that false-confidence failure mode.
# ──────────────────────────────────────────────

class TestPptReader:
    def test_extracts_real_content_from_fixture(self):
        """fixtures/sample.ppt is a genuine legacy OLE .ppt (LibreOffice `MS PowerPoint 97`
        export of a python-pptx-authored deck) — not a mock."""
        from rag_api.pipeline.step.parser.ppt import PptReader

        docs = PptReader().load_data(FIXTURES_DIR / "sample.ppt")

        assert "Test Presentation" in docs[0].text
        assert "Hello from a legacy PPT fixture." in docs[0].text

    def test_not_an_ole_file_raises_ingest_validation_error(self):
        from rag_api.pipeline.step.parser.ppt import PptReader

        path = _write(".ppt", "not an OLE file, just plain text")
        try:
            with pytest.raises(IngestValidationError):
                PptReader().load_data(path)
        finally:
            path.unlink(missing_ok=True)

    def test_registered_as_default_for_ppt(self):
        parsers = parser_registry.get_parsers()
        from rag_api.pipeline.step.parser.ppt import PptReader

        assert isinstance(parsers[".ppt"], PptReader)


class TestPptTextRecordExtraction:
    """Unit-level checks for the binary record parsing helper, independent of the OLE
    container layer — pins down the record-header math (see ppt.py module docstring for the
    off-by-one this replaced)."""

    def test_extracts_text_bytes_atom(self):
        from rag_api.pipeline.step.parser.ppt import PptReader

        text = "Hi"
        payload = text.encode("utf-16-le")
        record = b"\x00\x00" + b"\xa0\x0f" + len(payload).to_bytes(4, "little") + payload
        assert PptReader._extract_text_records(record) == [text]

    def test_ignores_bytes_before_first_marker(self):
        from rag_api.pipeline.step.parser.ppt import PptReader

        text = "Hi"
        payload = text.encode("utf-16-le")
        record = b"\x00\x00" + b"\xa0\x0f" + len(payload).to_bytes(4, "little") + payload
        assert PptReader._extract_text_records(b"garbage" + record) == [text]

    def test_no_marker_returns_empty(self):
        from rag_api.pipeline.step.parser.ppt import PptReader

        assert PptReader._extract_text_records(b"no markers here") == []
