"""upsert Op — Qdrant 기존 청크 삭제 후 신규 청크 배치 삽입."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass

from qdrant_client.http import models as qmodels

from infra import qdrant as qdrant_infra
from pipeline.ops.embed import EmbeddedNode

logger = logging.getLogger(__name__)


@dataclass
class UpsertResult:
    kb_id: str
    object_key: str
    chunk_count: int
    doc_key: str


def upsert(
    kb_id: str,
    object_key: str,
    embedded_nodes: list[EmbeddedNode],
) -> UpsertResult:
    """
    1. 기존 청크 전체 삭제 (doc_key 필터)
    2. 신규 청크 배치 삽입 (Dense + Sparse 벡터)
    """
    client = qdrant_infra.get_qdrant_client()
    doc_key = qdrant_infra.make_doc_key(kb_id, object_key)
    indexed_at = datetime.now(timezone.utc).isoformat()

    # 컬렉션 보장
    qdrant_infra.ensure_collection(kb_id, client)

    # 기존 청크 삭제
    qdrant_infra.delete_chunks_by_doc(kb_id, object_key, client)

    # Qdrant PointStruct 변환
    points: list[qmodels.PointStruct] = []
    for en in embedded_nodes:
        node = en.node
        meta = node.metadata

        payload = {
            "kb_id": kb_id,
            "doc_key": doc_key,
            "doc_type": meta.get("doc_type", ""),
            "object_key": object_key,
            "chunk_index": meta.get("chunk_index", 0),
            "page_num": meta.get("page_label", None),
            "total_chunks": meta.get("total_chunks", len(embedded_nodes)),
            "text": node.get_content(),
            "embedding_model": meta.get("embedding_model", ""),
            "embedding_provider": meta.get("embedding_provider", ""),
            "chunk_strategy": meta.get("chunk_strategy", ""),
            "chunk_size": meta.get("chunk_size", 0),
            "chunk_overlap": meta.get("chunk_overlap", 0),
            "indexed_at": indexed_at,
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

    qdrant_infra.upsert_chunks(kb_id, points, client)

    logger.info("Upsert done: kb=%s key=%s chunks=%d", kb_id, object_key, len(points))
    return UpsertResult(
        kb_id=kb_id,
        object_key=object_key,
        chunk_count=len(points),
        doc_key=doc_key,
    )