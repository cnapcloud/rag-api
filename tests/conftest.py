"""pytest fixtures — Mock Resources."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest


# ──────────────────────────────────────────────
# Fake Postgres store
# ──────────────────────────────────────────────

class FakePostgresStore:
    """In-memory implementation of infra.postgres CRUD functions (new doc_id-based API)."""

    def __init__(self):
        self._kbs: dict[str, dict] = {}
        self._docs: dict[str, dict] = {}  # keyed by doc_id
        self._connectors: dict[str, dict] = {}  # keyed by connector_id

    # -- KB --

    def register_kb(self, kb_id: str, kb_name: str = "", description: str | None = None, tags: list[str] | None = None) -> None:
        if kb_id not in self._kbs:
            self._kbs[kb_id] = {
                "kb_id": kb_id,
                "kb_name": kb_name,
                "description": description,
                "tags": tags or [],
                "status": "active",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

    def get_kb_meta(self, kb_id: str) -> dict | None:
        return dict(self._kbs[kb_id]) if kb_id in self._kbs else None

    def list_kb_ids(self) -> list[str]:
        return sorted(self._kbs.keys())

    def update_kb_meta(self, kb_id: str, kb_name: str | None = None, description: str | None = None, tags: list[str] | None = None) -> None:
        if kb_id not in self._kbs:
            return
        if kb_name is not None:
            self._kbs[kb_id]["kb_name"] = kb_name
        if description is not None:
            self._kbs[kb_id]["description"] = description
        if tags is not None:
            self._kbs[kb_id]["tags"] = tags
        self._kbs[kb_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def update_kb_status(self, kb_id: str, status: str) -> None:
        if kb_id in self._kbs:
            self._kbs[kb_id]["status"] = status

    def delete_kb_meta(self, kb_id: str) -> None:
        self._kbs.pop(kb_id, None)
        to_del = [doc_id for doc_id, d in self._docs.items() if d["kb_id"] == kb_id]
        for doc_id in to_del:
            del self._docs[doc_id]

    # -- Document --

    def create_doc(
        self,
        kb_id: str,
        source: str,
        title: str,
        source_type: str,
        *,
        status: str = "pending",
        storage_key: str | None = None,
        content_version: str | None = None,
        connector_id: str | None = None,
        file_size: int | None = None,
        doc_type: str | None = None,
    ) -> dict:
        doc_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "doc_id": doc_id,
            "kb_id": kb_id,
            "title": title,
            "source_type": source_type,
            "source": source,
            "storage_key": storage_key,
            "content_version": content_version,
            "connector_id": connector_id,
            "status": status,
            "deleted_at": None,
            "run_id": "",
            "error": None,
            "created_at": now,
            "updated_at": now,
            "process_started_at": None,
            "process_finished_at": None,
            "chunk_count": None,
            "file_size": file_size,
            "doc_type": doc_type,
            "embedding_model": None,
            "doc_created_at": None,
            "title_hash": None,
            "content_simhash": None,
        }
        self._docs[doc_id] = doc
        return dict(doc)

    def get_doc_by_id(self, doc_id: str) -> dict | None:
        return dict(self._docs[doc_id]) if doc_id in self._docs else None

    def get_doc_by_source(self, kb_id: str, source: str) -> dict | None:
        for doc in self._docs.values():
            if doc["kb_id"] == kb_id and doc["source"] == source:
                return dict(doc)
        return None

    def update_doc_fields(self, doc_id: str, fields: dict[str, Any]) -> None:
        if doc_id not in self._docs:
            return
        for k, v in fields.items():
            self._docs[doc_id][k] = v
        self._docs[doc_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def soft_delete_doc(self, doc_id: str) -> None:
        if doc_id in self._docs:
            self._docs[doc_id]["status"] = "deleted"
            self._docs[doc_id]["deleted_at"] = datetime.now(timezone.utc).isoformat()
            self._docs[doc_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def list_docs(self, kb_id: str, *, include_deleted: bool = False, status_filter: str | None = None) -> list[dict]:
        result = []
        for doc in self._docs.values():
            if doc["kb_id"] != kb_id:
                continue
            if not include_deleted and doc["status"] == "deleted":
                continue
            if status_filter is not None and doc["status"] != status_filter:
                continue
            result.append(dict(doc))
        result.sort(key=lambda d: d.get("created_at") or "", reverse=True)
        return result

    def list_docs_paginated(
        self,
        kb_id: str,
        page: int,
        page_size: int,
        status: str | None = None,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        include_deleted: bool = False,
    ) -> tuple[list[dict], int]:
        docs = self.list_docs(kb_id, include_deleted=include_deleted)

        if status:
            docs = [d for d in docs if d.get("status") == status]
        if search:
            docs = [d for d in docs if search.lower() in (d.get("title") or "").lower()]

        null_last_fields = {"chunk_count", "file_size"}
        reverse = sort_order == "desc"

        def _sort_key(d: dict):
            v = d.get(sort_by)
            if sort_by in null_last_fields:
                return (0 if v is not None else 1, -(v or 0) if reverse else (v or 0))
            return (0, (v or ""))

        docs.sort(key=_sort_key)
        if sort_by not in null_last_fields:
            docs.sort(key=lambda d: d.get(sort_by) or "", reverse=reverse)

        total = len(docs)
        offset = (page - 1) * page_size
        return docs[offset: offset + page_size], total

    def ping(self) -> bool:
        return True

    def run_migrations(self) -> None:
        pass

    # -- Connector --

    def create_connector(
        self,
        connector_id: str,
        kb_id: str,
        name: str,
        source_type: str,
        config: dict,
        sync_schedule: str | None = None,
        schedule_enabled: bool = False,
    ) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        connector = {
            "connector_id": connector_id,
            "kb_id": kb_id,
            "name": name,
            "source_type": source_type,
            "config": config,
            "sync_schedule": sync_schedule,
            "schedule_enabled": schedule_enabled,
            "sync_status": "idle",
            "sync_started_at": None,
            "last_synced_at": None,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        self._connectors[connector_id] = connector
        return dict(connector)

    def get_connector(self, connector_id: str) -> dict | None:
        c = self._connectors.get(connector_id)
        return dict(c) if c else None

    def list_connectors(
        self,
        kb_id: str | None = None,
        source_type: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        result = []
        for c in self._connectors.values():
            if kb_id is not None and c["kb_id"] != kb_id:
                continue
            if source_type is not None and c["source_type"] != source_type:
                continue
            if status is not None and c["status"] != status:
                continue
            result.append(dict(c))
        result.sort(key=lambda c: c.get("created_at") or "", reverse=True)
        return result

    def update_connector(self, connector_id: str, fields: dict) -> dict | None:
        allowed = {"name", "config", "sync_schedule", "schedule_enabled", "status"}
        if connector_id not in self._connectors:
            return None
        for k, v in fields.items():
            if k in allowed:
                self._connectors[connector_id][k] = v
        self._connectors[connector_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(self._connectors[connector_id])

    def delete_connector(self, connector_id: str) -> None:
        self._connectors.pop(connector_id, None)

    def set_connector_sync_status(
        self,
        connector_id: str,
        sync_status: str,
        last_synced_at: datetime | None = None,
    ) -> None:
        if connector_id not in self._connectors:
            return
        self._connectors[connector_id]["sync_status"] = sync_status
        if sync_status == "running":
            self._connectors[connector_id]["sync_started_at"] = datetime.now(timezone.utc).isoformat()
        else:
            self._connectors[connector_id]["sync_started_at"] = None
        if last_synced_at is not None:
            self._connectors[connector_id]["last_synced_at"] = last_synced_at.isoformat()
        self._connectors[connector_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def set_connector_status(self, connector_id: str, status: str) -> None:
        if connector_id in self._connectors:
            self._connectors[connector_id]["status"] = status
            self._connectors[connector_id]["updated_at"] = datetime.now(timezone.utc).isoformat()

    def get_connector_doc_counts(self, connector_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for doc in self._docs.values():
            if doc.get("connector_id") != connector_id:
                continue
            counts[doc["status"]] = counts.get(doc["status"], 0) + 1
        counts["total"] = sum(counts.values())
        return counts

    def list_docs_by_connector(self, connector_id: str, *, include_deleted: bool = False) -> list[dict]:
        result = []
        for doc in self._docs.values():
            if doc.get("connector_id") != connector_id:
                continue
            if not include_deleted and doc["status"] == "deleted":
                continue
            result.append(dict(doc))
        result.sort(key=lambda d: d.get("created_at") or "", reverse=True)
        return result

    def list_docs_by_connector_paginated(
        self,
        connector_id: str,
        page: int,
        page_size: int,
        status: str | None = None,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        include_deleted: bool = False,
    ) -> tuple[list[dict], int]:
        docs = self.list_docs_by_connector(connector_id, include_deleted=include_deleted)
        if status:
            docs = [d for d in docs if d.get("status") == status]
        if search:
            docs = [d for d in docs if search.lower() in (d.get("title") or "").lower()]
        docs.sort(key=lambda d: d.get(sort_by) or "", reverse=(sort_order == "desc"))
        total = len(docs)
        offset = (page - 1) * page_size
        return docs[offset: offset + page_size], total


@pytest.fixture
def mock_postgres(monkeypatch):
    """In-memory Postgres substitute (new doc_id-based API)."""
    store = FakePostgresStore()
    monkeypatch.setattr("rag_api.infra.postgres.register_kb", store.register_kb)
    monkeypatch.setattr("rag_api.infra.postgres.get_kb_meta", store.get_kb_meta)
    monkeypatch.setattr("rag_api.infra.postgres.list_kb_ids", store.list_kb_ids)
    monkeypatch.setattr("rag_api.infra.postgres.update_kb_meta", store.update_kb_meta)
    monkeypatch.setattr("rag_api.infra.postgres.update_kb_status", store.update_kb_status)
    monkeypatch.setattr("rag_api.infra.postgres.delete_kb_meta", store.delete_kb_meta)
    monkeypatch.setattr("rag_api.infra.postgres.create_doc", store.create_doc)
    monkeypatch.setattr("rag_api.infra.postgres.get_doc_by_id", store.get_doc_by_id)
    monkeypatch.setattr("rag_api.infra.postgres.get_doc_by_source", store.get_doc_by_source)
    monkeypatch.setattr("rag_api.infra.postgres.update_doc_fields", store.update_doc_fields)
    monkeypatch.setattr("rag_api.infra.postgres.soft_delete_doc", store.soft_delete_doc)
    monkeypatch.setattr("rag_api.infra.postgres.list_docs", store.list_docs)
    monkeypatch.setattr("rag_api.infra.postgres.list_docs_paginated", store.list_docs_paginated)
    monkeypatch.setattr("rag_api.infra.postgres.list_docs_by_connector", store.list_docs_by_connector)
    monkeypatch.setattr("rag_api.infra.postgres.list_docs_by_connector_paginated", store.list_docs_by_connector_paginated)
    monkeypatch.setattr("rag_api.infra.postgres.ping", store.ping)
    monkeypatch.setattr("rag_api.infra.postgres.run_migrations", store.run_migrations)
    monkeypatch.setattr("rag_api.infra.postgres.create_connector", store.create_connector)
    monkeypatch.setattr("rag_api.infra.postgres.get_connector", store.get_connector)
    monkeypatch.setattr("rag_api.infra.postgres.list_connectors", store.list_connectors)
    monkeypatch.setattr("rag_api.infra.postgres.update_connector", store.update_connector)
    monkeypatch.setattr("rag_api.infra.postgres.delete_connector", store.delete_connector)
    monkeypatch.setattr("rag_api.infra.postgres.set_connector_sync_status", store.set_connector_sync_status)
    monkeypatch.setattr("rag_api.infra.postgres.set_connector_status", store.set_connector_status)
    monkeypatch.setattr("rag_api.infra.postgres.get_connector_doc_counts", store.get_connector_doc_counts)
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
    from rag_api.defs.resources.resources import (
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
