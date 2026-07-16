"""parser.extensions — extension/format constants.

Kept free of reader-class imports so downstream consumers that only need extension
membership (chunk.py's code-vs-text split, dedup/__init__.py's document-type gate) can
import this module without pulling in trafilatura/PyMuPDF/docutils/etc.
"""

from __future__ import annotations

DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".md", ".docx", ".doc", ".txt", ".hwp", ".html", ".htm", ".rst", ".eml",
    ".csv", ".tsv", ".json", ".epub", ".xlsx", ".xls", ".pptx", ".ppt",
})

CODE_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".java", ".rs",
    ".cpp", ".cc", ".c", ".cs",
    ".rb", ".php", ".swift", ".kt", ".scala", ".sh",
})

CONFIG_DATA_EXTENSIONS: frozenset[str] = frozenset({
    ".yaml", ".yml", ".properties",
})

CODE_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".cpp": "cpp", ".cc": "cpp",
    ".c": "c",
    ".cs": "c_sharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".scala": "scala",
    ".sh": "bash",
}
