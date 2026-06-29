"""pipeline/ops/meta.py — Re-exports from pipeline.utils.doc_state.

State transition logic has moved to pipeline/utils/doc_state.py.
This module exists for backward compatibility with existing callers.
"""

from rag_api.pipeline.utils.doc_state import (  # noqa: F401
    restore_indexed,
    set_deleting,
    set_failed,
    set_indexed as update_meta,
    set_pending,
    set_processing,
)
