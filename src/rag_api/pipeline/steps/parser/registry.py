"""parser.registry — extension-point registry for pipeline/steps/parse.py file readers.

See docs/internal/design/parser-registry.md for the architecture. parse.py's built-in readers
and any settings-configured plugins are registered through the same API (register_parser) —
there is no privileged path for defaults, so a plugin can freely add, replace, or remove any
of them.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from pathlib import Path

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

from rag_api.exceptions import ConfigError

logger = logging.getLogger(__name__)

PostProcessor = Callable[[list[Document], Path, str, str | None], list[Document]]

_parsers: dict[str, BaseReader] = {}
_post_processors: list[PostProcessor] = []
_loaded = False


def register_parser(ext: str, reader: BaseReader) -> None:
    """Register a reader for an extension. Replaces any existing registration for that ext."""
    _parsers[ext] = reader


def unregister_parser(ext: str) -> None:
    """Remove a registered extension. No-op if it was never registered."""
    _parsers.pop(ext, None)


def register_post_processor(fn: PostProcessor) -> None:
    """Register a function applied to every parsed document set after reader.load_data().

    Its return value is additional Documents to append (e.g. image captions), not a
    replacement for the parsed text documents.
    """
    _post_processors.append(fn)


def get_parsers() -> dict[str, BaseReader]:
    _ensure_loaded()
    return dict(_parsers)


def get_post_processors() -> list[PostProcessor]:
    _ensure_loaded()
    return list(_post_processors)


def supported_extensions() -> frozenset[str]:
    _ensure_loaded()
    return frozenset(_parsers)


def reset_registry() -> None:
    """Test-only: clear all state and force _register_defaults()/plugin reload on next access."""
    global _loaded
    _parsers.clear()
    _post_processors.clear()
    _loaded = False


def _register_defaults() -> None:
    from rag_api.pipeline.steps.parser.doc import DocReader
    from rag_api.pipeline.steps.parser.eml import EmlReader
    from rag_api.pipeline.steps.parser.extensions import CODE_EXTENSIONS, CONFIG_DATA_EXTENSIONS
    from rag_api.pipeline.steps.parser.html import HTMLCleanReader
    from rag_api.pipeline.steps.parser.pdf import PyMuPDFReader
    from rag_api.pipeline.steps.parser.ppt import PptReader
    from rag_api.pipeline.steps.parser.rst import RstReader
    from rag_api.pipeline.steps.parser.tsv import TsvReader

    try:
        from llama_index.core.readers.json import JSONReader
        from llama_index.readers.file import (
            CSVReader,
            DocxReader,
            EpubReader,
            FlatReader,
            MarkdownReader,
            PandasExcelReader,
            PptxReader,
        )
        from llama_index.readers.hwp import HWPReader
    except ImportError:
        logger.warning("llama-index-readers-file not installed, default parsers not registered")
        return

    register_parser(".pdf", PyMuPDFReader())
    register_parser(".md", MarkdownReader())
    register_parser(".docx", DocxReader())
    register_parser(".doc", DocReader())
    register_parser(".txt", FlatReader())
    register_parser(".hwp", HWPReader())
    register_parser(".html", HTMLCleanReader())
    register_parser(".htm", HTMLCleanReader())
    register_parser(".rst", RstReader())
    register_parser(".eml", EmlReader())
    register_parser(".csv", CSVReader())
    register_parser(".tsv", TsvReader())
    register_parser(".json", JSONReader())
    register_parser(".epub", EpubReader())
    register_parser(".xlsx", PandasExcelReader())
    register_parser(".xls", PandasExcelReader())
    register_parser(".pptx", PptxReader())
    register_parser(".ppt", PptReader())
    for ext in CODE_EXTENSIONS | CONFIG_DATA_EXTENSIONS:
        register_parser(ext, FlatReader())


def _load_plugins() -> None:
    from rag_api.config.settings import get_settings

    for dotted in get_settings().ingestion.parser_plugins:
        module_path, _, fn_name = dotted.partition(":")
        if not module_path or not fn_name:
            raise ConfigError(
                f"Invalid parser_plugins entry (expected 'module.path:func'): {dotted!r}"
            )
        try:
            module = importlib.import_module(module_path)
            register_fn = getattr(module, fn_name)
        except (ImportError, AttributeError) as e:
            raise ConfigError(f"Failed to load parser plugin {dotted!r}: {e}") from e
        register_fn()
        logger.info("Parser plugin loaded: %s", dotted)


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _register_defaults()
    _load_plugins()
    _loaded = True
