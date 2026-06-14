"""pytest fixtures — Mock Resources."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ──────────────────────────────────────────────
# Mock 인프라 클라이언트
# ──────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """In-memory Redis 대체."""
    store: dict = {}

    class FakeRedis:
        def hset(self, key, mapping=None, **kw):
            if key not in store:
                store[key] = {}
            if mapping:
                store[key].update({k: str(v) for k, v in mapping.items()})

        def hsetnx(self, key, field, value):
            if key not in store:
                store[key] = {}
            if field not in store[key]:
                store[key][field] = str(value)

        def hget(self, key, field):
            return store.get(key, {}).get(field)

        def hgetall(self, key):
            return dict(store.get(key, {}))

        def delete(self, *keys):
            for k in keys:
                store.pop(k, None)

        def sadd(self, key, *values):
            if key not in store:
                store[key] = set()
            store[key].update(values)

        def smembers(self, key):
            return store.get(key, set())

        def srem(self, key, *values):
            if key in store:
                store[key].difference_update(values)

        def exists(self, key):
            return key in store

        def keys(self, pattern="*"):
            import fnmatch
            return [k for k in store.keys() if fnmatch.fnmatch(k, pattern)]

        def ping(self):
            return True

        def rpop(self, key):
            lst = store.get(key, [])
            if lst:
                return lst.pop()
            return None

        def lpush(self, key, value):
            if key not in store:
                store[key] = []
            store[key].insert(0, value)

    return FakeRedis()


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant 클라이언트."""
    client = MagicMock()
    client.get_collections.return_value = MagicMock(collections=[])
    client.upsert.return_value = MagicMock(status="completed")
    client.delete.return_value = MagicMock(status="completed")
    return client


@pytest.fixture
def mock_minio():
    """Mock MinIO 클라이언트."""
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
# Dagster 통합 테스트용 Mock Resources
# ──────────────────────────────────────────────

@pytest.fixture
def mock_dagster_resources(mock_redis, mock_qdrant, mock_minio):
    from dagster_pipeline.resources.resources import (
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