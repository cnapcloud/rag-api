"""parser.html — HTML reader (moved from parse.py, no behavior change)."""

from __future__ import annotations

from pathlib import Path

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader


class HTMLCleanReader(BaseReader):
    """HTML reader that extracts main content via trafilatura's density-based
    algorithm instead of a tag-name deny-list, since markup conventions vary
    too much across sites for deny-listing to reliably strip boilerplate.

    html_extraction_policy (settings.ingestion.html_extraction_policy) picks how
    trafilatura treats ambiguous blocks (sidebar-or-content boundary cases):
    "strict" excludes them (favors dedup stage 1 SimHash consistency over
    completeness), "lenient" includes them (favors completeness — default,
    since strict was found to drop 90%+ of the body on wiki-style pages
    with heavy footnote/TOC/collapsible markup), "balanced" is neutral.
    output_format="markdown" preserves heading/list structure for downstream
    chunking, instead of flattening everything with get_text().
    """

    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        import trafilatura

        from rag_api.config.settings import get_settings

        with open(file, encoding="utf-8") as f:
            html = f.read()

        policy = get_settings().ingestion.html_extraction_policy
        text = (
            trafilatura.extract(
                html,
                favor_precision=(policy == "strict"),
                favor_recall=(policy == "lenient"),
                output_format="markdown",
                include_tables=True,
            )
            or ""
        )

        metadata: dict = {"file_path": str(file)}
        metadata.update(extra_info or {})

        return [Document(text=text, metadata=metadata)]
