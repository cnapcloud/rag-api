"""Qdrant client factory and collection/chunk management."""

from __future__ import annotations

import logging

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from config.settings import get_settings
from exceptions import ConfigError

logger = logging.getLogger(__name__)

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

_client: QdrantClient | None = None


# ──────────────────────────────────────────────
# Client factory
# ──────────────────────────────────────────────

def get_qdrant_client() -> QdrantClient:
    global _client
    if _client is None:
        cfg = get_settings().qdrant
        host = cfg.host
        if host.startswith("http://") or host.startswith("https://"):
            url = host
        else:
            scheme = "http" if cfg.insecure else "https"
            url = f"{scheme}://{host}:{cfg.port}"
        _client = QdrantClient(url=url, verify=not cfg.insecure, check_compatibility=True)
    return _client


# ──────────────────────────────────────────────
# Health check
# ──────────────────────────────────────────────

def ping() -> bool:
    try:
        get_qdrant_client().get_collections()
        return True
    except Exception as e:
        logger.warning("Qdrant ping failed: %s", e)
        return False


# ──────────────────────────────────────────────
# Collection management
# ──────────────────────────────────────────────

def ensure_collection(
    kb_id: str,
    client: QdrantClient | None = None,
) -> None:
    c = client or get_qdrant_client()
    vector_size = get_settings().embedding.vector_size
    try:
        info = c.get_collection(kb_id)
        existing_size = info.config.params.vectors[DENSE_VECTOR_NAME].size
        if existing_size != vector_size:
            raise ConfigError(
                f"Collection '{kb_id}' has vector_size={existing_size} "
                f"but settings.embedding.vector_size={vector_size}. "
                "Drop and re-create the collection, then re-index all documents."
            )
        return
    except ConfigError:
        raise
    except Exception:
        pass
    c.create_collection(
        collection_name=kb_id,
        vectors_config={
            DENSE_VECTOR_NAME: qmodels.VectorParams(
                size=vector_size,
                distance=qmodels.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
                modifier=qmodels.Modifier.IDF,
            ),
        },
    )
    logger.info("Qdrant collection created: %s", kb_id)


def drop_collection(
    kb_id: str,
    client: QdrantClient | None = None,
) -> None:
    c = client or get_qdrant_client()
    c.delete_collection(kb_id)
    logger.info("Qdrant collection dropped: %s", kb_id)


# ──────────────────────────────────────────────
# Chunk CRUD
# ──────────────────────────────────────────────

def delete_chunks_by_doc_id(
    kb_id: str,
    doc_id: str,
    client: QdrantClient | None = None,
) -> None:
    c = client or get_qdrant_client()
    c.delete(
        collection_name=kb_id,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="doc_id",
                        match=qmodels.MatchValue(value=doc_id),
                    )
                ]
            )
        ),
    )
    logger.info("Qdrant chunks deleted: kb=%s doc_id=%s", kb_id, doc_id)


def upsert_chunks(
    kb_id: str,
    points: list[qmodels.PointStruct],
    client: QdrantClient | None = None,
) -> None:
    c = client or get_qdrant_client()
    c.upsert(collection_name=kb_id, points=points)
    logger.info("Qdrant upsert done: kb=%s count=%d", kb_id, len(points))
