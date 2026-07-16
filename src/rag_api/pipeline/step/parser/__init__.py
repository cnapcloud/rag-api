"""pipeline/step/parser — extension-point registry package for parse.py file readers.

See docs/internal/design/parser-registry.md for the architecture. This package re-exports
the registration API (registry.py) as its public surface; individual reader modules
(html.py/pdf.py/rst.py/eml.py/tsv.py) and extensions.py are imported directly by callers
that need those specific symbols (e.g. tests, chunk.py).
"""

from __future__ import annotations

from rag_api.pipeline.step.parser.registry import (
    get_parsers,
    get_post_processors,
    register_parser,
    register_post_processor,
    reset_registry,
    supported_extensions,
    unregister_parser,
)

__all__ = [
    "get_parsers",
    "get_post_processors",
    "register_parser",
    "register_post_processor",
    "reset_registry",
    "supported_extensions",
    "unregister_parser",
]
