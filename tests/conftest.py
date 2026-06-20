"""pytest fixtures — Mock Resources."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────
# Fake Postgres store
# ──────────────────────────────────────────────

class FakePostgresStore:
    """In-memory implementation of infra.postgres CRUD functions."""

    def __init__(self):
        self._kbs: dict[str, dict] = {}
        self._docs: dict[tuple, dict] = {}

    def register_kb(self, kb_id: str, description: str = "") -> None:
        if kb_id not in self._kbs:
            self._kbs[kb_id] = {
                "kb_id": kb_id,
                "description": description,
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

    def get_kb_meta(self, kb_id: str) -> dict | None:
        return dict(self._kbs[kb_id]) if kb_id in self._kbs else None

    def list_kb_ids(self) -> list[str]:
        return sorted(self._kbs.keys())

    def update_kb_status(self, kb_id: str, status: str) -> None:
        if kb_id in self._kbs:
            self._kbs[kb_id]["status"] = status

    def delete_kb_meta(self, kb_id: str) -> None:
        self._kbs.pop(kb_id, None)
        keys_to_del = [k for k in self._docs if k[0] == kb_id]
        for k in keys_to_del:
            del self._docs[k]

    def set_doc_status(self, kb_id: str, doc_source: str, fields: dict) -> None:
        key = (kb_id, doc_source)
        if key not in self._docs:
            self._docs[key] = {
                "status": "", "etag": "", "run_id": "", "error": "",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": "", "chunk_count": "", "file_size": "",
                "doc_type": "", "embedding_model": "", "doc_created_at": "",
            }
        for k, v in fields.items():
            self._docs[key][k] = str(v) if v is not None else ""

    def get_doc_status(self, kb_id: str, doc_source: str) -> dict | None:
        return dict(self._docs.get((kb_id, doc_source), {})) or None

    def list_docs(self, kb_id: str) -> list[dict]:
        return [
            {"doc_source": k[1], **dict(v)}
            for k, v in self._docs.items()
            if k[0] == kb_id
        ]

    def list_docs_by_status(self, kb_id: str, status: str) -> list[dict]:
        return [d for d in self.list_docs(kb_id) if d.get("status") == status]

    def list_docs_paginated(
        self,
        kb_id: str,
        page: int,
        page_size: int,
        status: str | None = None,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> tuple[list[dict], int]:
        docs = self.list_docs(kb_id)

        if status:
            docs = [d for d in docs if d.get("status") == status]

        if search:
            docs = [d for d in docs if search.lower() in (d.get("doc_source") or "").lower()]

        null_last_fields = {"chunk_count", "file_size"}
        reverse = sort_order == "desc"

        def _sort_key(d: dict):
            v = d.get(sort_by)
            if sort_by in null_last_fields:
                try:
                    parsed = int(v) if v not in (None, "") else None
                except (TypeError, ValueError):
                    parsed = None
                if parsed is None:
                    return (1, 0)
                return (0, parsed if not reverse else -parsed)
            return (0, (v or ""))

        docs.sort(key=_sort_key, reverse=False)
        if sort_by not in null_last_fields:
            docs.sort(key=lambda d: d.get(sort_by) or "", reverse=reverse)

        total = len(docs)
        offset = (page - 1) * page_size
        return docs[offset : offset + page_size], total

    def get_doc_etag(self, kb_id: str, doc_source: str) -> str | None:
        doc = self._docs.get((kb_id, doc_source))
        return doc.get("etag") or None if doc else None

    def set_doc_etag(self, kb_id: str, doc_source: str, etag: str) -> None:
        self.set_doc_status(kb_id, doc_source, {"etag": etag})

    def delete_doc_etag(self, kb_id: str, doc_source: str) -> None:
        doc = self._docs.get((kb_id, doc_source))
        if doc:
            doc["etag"] = ""

    def delete_doc_meta(self, kb_id: str, doc_source: str) -> None:
        self._docs.pop((kb_id, doc_source), None)

    def ping(self) -> bool:
        return True

    def run_migrations(self) -> None:
        pass


@pytest.fixture
def mock_postgres(monkeypatch):
    """In-memory Postgres substitute."""
    store = FakePostgresStore()
    monkeypatch.setattr("infra.postgres.register_kb", store.register_kb)
    monkeypatch.setattr("infra.postgres.get_kb_meta", store.get_kb_meta)
    monkeypatch.setattr("infra.postgres.list_kb_ids", store.list_kb_ids)
    monkeypatch.setattr("infra.postgres.update_kb_status", store.update_kb_status)
    monkeypatch.setattr("infra.postgres.delete_kb_meta", store.delete_kb_meta)
    monkeypatch.setattr("infra.postgres.set_doc_status", store.set_doc_status)
    monkeypatch.setattr("infra.postgres.get_doc_status", store.get_doc_status)
    monkeypatch.setattr("infra.postgres.list_docs", store.list_docs)
    monkeypatch.setattr("infra.postgres.list_docs_by_status", store.list_docs_by_status)
    monkeypatch.setattr("infra.postgres.list_docs_paginated", store.list_docs_paginated)
    monkeypatch.setattr("infra.postgres.get_doc_etag", store.get_doc_etag)
    monkeypatch.setattr("infra.postgres.set_doc_etag", store.set_doc_etag)
    monkeypatch.setattr("infra.postgres.delete_doc_etag", store.delete_doc_etag)
    monkeypatch.setattr("infra.postgres.delete_doc_meta", store.delete_doc_meta)
    monkeypatch.setattr("infra.postgres.ping", store.ping)
    monkeypatch.setattr("infra.postgres.run_migrations", store.run_migrations)
    return store


# ──────────────────────────────────────────────
# Mock Redis — queue only
# ──────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """In-memory Redis substitute — queue operations only."""
    lists: dict = {}

    class FakeRedis:
        def rpop(self, key):
            lst = lists.get(key, [])
            return lst.pop() if lst else None

        def lpush(self, key, value):
            lists.setdefault(key, []).insert(0, value)

        def ping(self):
            return True

    return FakeRedis()


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant client."""
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[])
    client.upsert.return_value = MagicMock(status="completed")
    client.delete.return_value = MagicMock(status="completed")
    return client


@pytest.fixture
def mock_minio():
    """Mock MinIO client."""
    client = MagicMock()
    client.bucket_exists.return_value = True
    client.list_objects.return_value = []
    return client


@pytest.fixture
def mock_embed_model():
    """Mock LlamaIndex Embedding."""
    model = MagicMock()
    model.get_text_embedding_batch.return_value = [[0.1] * 1024]
    model.get_text_embedding.return_value = [0.1] * 1024
    return model


# ──────────────────────────────────────────────
# Dagster integration test mock resources
# ──────────────────────────────────────────────

@pytest.fixture
def mock_dagster_resources(mock_redis, mock_qdrant, mock_minio):
    from defs.resources.resources import (
        EmbeddingResource,
        MinIOResource,
        QdrantResource,
        RedisResource,
    )

    class MockMinIOResource(MinIOResource):
        def get_client(self):
            return mock_minio

    class MockQdrantResource(QdrantResource):
        def get_client(self):
            return mock_qdrant

    class MockRedisResource(RedisResource):
        def get_client(self):
            return mock_redis

    return {
        "minio": MockMinIOResource(endpoint="http://localhost:9000", access_key="", secret_key="", bucket="test"),
        "qdrant": MockQdrantResource(host="localhost", port=6333),
        "redis": MockRedisResource(host="localhost", port=6379),
        "embedding": EmbeddingResource(provider="ollama", model="bge-m3"),
    }
