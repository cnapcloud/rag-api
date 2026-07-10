"""upsert Op — delete existing chunks for a doc then batch-insert new ones."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from qdrant_client.http import models as qmodels

from rag_api.infra import qdrant as qdrant_infra
from rag_api.pipeline.ops.embed import EmbeddedNode

logger = logging.getLogger(__name__)


@dataclass
class UpsertResult:
    kb_id: str
    doc_id: str
    chunk_count: int
    doc_created_at: str = ""


def upsert(
    kb_id: str,
    doc_id: str,
    embedded_nodes: list[EmbeddedNode],
    title: str = "",
    source_type: str = "",
    source: str = "",
) -> UpsertResult:
    """Delete all existing chunks for doc_id then insert new ones."""
    client = qdrant_infra.get_qdrant_client()
    updated_at = datetime.now(timezone.utc).isoformat()

    qdrant_infra.ensure_collection(kb_id, client)
    qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id, client)

    doc_created_at = embedded_nodes[0].node.metadata.get("doc_created_at", "") if embedded_nodes else ""

    points: list[qmodels.PointStruct] = []
    for en in embedded_nodes:
        node = en.node
        meta = node.metadata

        payload = {
            "kb_id": kb_id,
            "doc_id": doc_id,
            "title": title,
            "source_type": source_type,
            "source": source,
            "doc_type": meta.get("doc_type", ""),
            "chunk_index": meta.get("chunk_index", 0),
            "page_num": meta.get("page_label", None),
            "total_chunks": meta.get("total_chunks", len(embedded_nodes)),
            "text": node.get_content(),
            "embedding_model": meta.get("embedding_model", ""),
            "embedding_provider": meta.get("embedding_provider", ""),
            "chunk_strategy": meta.get("chunk_strategy", ""),
            "chunk_size": meta.get("chunk_size", 0),
            "chunk_overlap": meta.get("chunk_overlap", 0),
            "updated_at": updated_at,
            "doc_created_at": doc_created_at,
        }

        points.append(
            qmodels.PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    qdrant_infra.DENSE_VECTOR_NAME: en.dense_vector,
                    qdrant_infra.SPARSE_VECTOR_NAME: qmodels.SparseVector(
                        indices=en.sparse_indices,
                        values=en.sparse_values,
                    ),
                },
                payload=payload,
            )
        )

    if points:
        qdrant_infra.upsert_chunks(kb_id, points, client)

    logger.info("Upsert done: kb=%s doc_id=%s chunks=%d", kb_id, doc_id, len(points))
    return UpsertResult(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_count=len(points),
        doc_created_at=doc_created_at,
    )
