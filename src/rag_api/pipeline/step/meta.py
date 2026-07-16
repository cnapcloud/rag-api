"""pipeline/step/meta.py — Ingest pipeline's final stage: build indexed metadata from upsert result.

set_indexed is the only status transition specific to this stage (called once, after upsert
succeeds). Other transitions (pending/processing/failed/deleting) are cross-cutting — used at
multiple points in the pipeline and by connectors/routers/queue outside it — so they live in and
should be imported directly from pipeline.utils.doc_state instead of through here.
"""

from rag_api.pipeline.utils.doc_state import set_indexed  # noqa: F401
