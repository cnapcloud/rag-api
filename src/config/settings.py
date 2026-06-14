"""설정 로더 — config/settings.yaml + 환경변수 오버라이드."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# ──────────────────────────────────────────────
# 하위 모델
# ──────────────────────────────────────────────

class S3Settings(BaseModel):
    endpoint: str = "http://minio:9000"
    access_key: str = ""
    secret_key: str = ""
    rag_bucket: str = "rag-api"
    dagster_bucket: str = "dagster-storage"
    region: str = "us-east-1"
    poll_interval_sec: int = 10
    insecure: bool = False


class RedisSettings(BaseModel):
    host: str = "redis"
    port: int = 6379
    password: str = ""
    db: int = 0


class QdrantSettings(BaseModel):
    host: str = "qdrant"
    port: int = 6333
    insecure: bool = False


class IngestionSettings(BaseModel):
    max_file_size_mb: int = 200
    max_workers: int = 4           # background mode concurrency limit
    poll_interval_sec: int = 5     # Redis queue poll interval (shared by both modes)
    max_runs_per_tick: int = 5     # max RunRequests per sensor tick (Dagster mode)
    processing_delay_sec: int = 10  # delay queue retry interval when doc is processing
    queue_worker_enabled: bool = True  # set false to disable QueueWorker


class ChunkingSettings(BaseModel):
    strategy: str = "recursive"   # recursive / semantic / document_aware (pending US-03)
    chunk_size: int = 1024
    chunk_overlap: int = 128
    semantic_threshold: float = 0.8


class EmbeddingSettings(BaseModel):
    provider: str = "ollama"           # ollama / openai
    model: str = "bge-m3"
    vector_size: int = 1024            # bge-m3=1024, text-embedding-3-small=1536, ada-002=1536
    ollama_url: str = "http://ollama:11434"
    openai_api_key: str = ""
    openai_model: str = "text-embedding-3-small"


class RerankerSettings(BaseModel):
    enabled: bool = True
    provider: str = "jina"
    api_key: str = ""
    model: str = "jina-reranker-v2-base-multilingual"
    top_n: int = 3
    timeout_sec: int = 5
    fallback_on_error: bool = True


class RetrievalSettings(BaseModel):
    mode: str = "hybrid"
    top_k: int = 10
    alpha: float = 0.5
    merge_strategy: str = "rrf"
    rerank: RerankerSettings = Field(default_factory=RerankerSettings)


class LogSettings(BaseModel):
    level: str = "INFO"   # DEBUG | INFO | WARNING | ERROR


class DagsterSettings(BaseModel):
    executor: str = "in_process"  # in_process | k8s


class McpSettings(BaseModel):
    enabled: bool = True
    transport: str = "stdio"   # stdio | sse | streamable-http
    host: str = "0.0.0.0"
    port: int = 8001


class KBDefinition(BaseModel):
    id: str
    description: str = ""


# ──────────────────────────────────────────────
# 메인 설정
# ──────────────────────────────────────────────

_SETTINGS_PATH = Path(__file__).parents[2] / "settings.yaml"


class Settings(BaseModel):
    s3: S3Settings = Field(default_factory=S3Settings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    dagster: DagsterSettings = Field(default_factory=DagsterSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    logging: LogSettings = Field(default_factory=LogSettings)
    knowledge_bases: list[KBDefinition] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path = _SETTINGS_PATH) -> "Settings":
        if path.exists():
            with open(path) as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
        else:
            data = {}

        if api_key := os.environ.get("OPENAI_API_KEY"):
            data.setdefault("embedding", {})["openai_api_key"] = api_key

        return cls.model_validate(data)


# 싱글턴
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_yaml()
    return _settings