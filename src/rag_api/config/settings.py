"""설정 로더 — config/settings.yaml + 환경변수 오버라이드."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

# ──────────────────────────────────────────────
# 하위 모델
# ──────────────────────────────────────────────

class ServerSettings(BaseModel):
    production: bool = False
    # Only used when production=true; a single reload-enabled process ignores this.
    workers: int = 1


class DagsterSettings(BaseModel):
    endpoint: str = "http://dagster-webserver:3000"


class S3Settings(BaseModel):
    endpoint: str = "http://minio:9000"
    access_key: str = ""
    secret_key: str = ""
    rag_bucket: str = "rag-api"
    dagster_bucket: str = "dagster-storage"
    region: str = "us-east-1"
    insecure: bool = False


class RedisSettings(BaseModel):
    host: str = "redis"
    port: int = 6379
    password: str = ""
    db: int = 0
    timeout_seconds: float = 2.0


class PostgresSettings(BaseModel):
    host: str = "localhost"
    port: int = 5432
    dbname: str = "rag-api"
    user: str = "dagster"
    password: str = "dagster"
    pool_size: int = 5
    connect_timeout: int = 30


class QdrantSettings(BaseModel):
    host: str = "qdrant"
    port: int = 6333
    insecure: bool = False


class IngestionSettings(BaseModel):
    max_file_size_mb: int = 200
    min_content_chars: int = 200
    # trafilatura extraction bias — see HTMLCleanReader (pipeline/step/parser/html.py).
    # strict: 애매한 블록 제외 (짧고 확실한 본문만) / lenient: 애매한 블록 포함 (본문 손실 최소화,
    # 짧은 boilerplate 잔존 가능) / balanced: 중립.
    html_extraction_policy: Literal["strict", "lenient", "balanced"] = "lenient"
    # "module.path:register_func" 목록 — pipeline/step/parser/registry.py가 지연 로드 시점에
    # 순서대로 import하여 각 register 함수를 호출한다. docs/internal/design/parser-registry.md 참고.
    parser_plugins: list[str] = Field(default_factory=list)


class QueueWorkerSettings(BaseModel):
    enabled: bool = True
    max_workers: int = 4


class QueuePollSettings(BaseModel):
    poll_interval_sec: int = 5
    max_per_poll: int = 5
    retry_interval_sec: int = 10


class ChunkingSettings(BaseModel):
    strategy: str = "recursive"   # recursive / semantic / document_aware (pending US-03)
    chunk_size: int = 1024
    chunk_overlap: int = 128
    semantic_threshold: float = 0.8
    min_chunk_chars: int = 30
    code_chunk_lines: int = 40
    code_chunk_lines_overlap: int = 5


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


class HybridSearchSettings(BaseModel):
    alpha: float = 0.5
    rrf_k: int = 60


class SimilaritySearchSettings(BaseModel):
    min_score: float = 0.0


class RetrievalSettings(BaseModel):
    mode: Literal["hybrid", "similarity"] = "hybrid"
    top_k: int = 10
    hybrid: HybridSearchSettings = Field(default_factory=HybridSearchSettings)
    similarity: SimilaritySearchSettings = Field(default_factory=SimilaritySearchSettings)
    rerank: RerankerSettings = Field(default_factory=RerankerSettings)


class LogSettings(BaseModel):
    level: str = "INFO"   # DEBUG | INFO | WARNING | ERROR
    # Top-level logger namespaces to eagerly configure (setup_logging()).
    # Must match real Python package names (underscore, not hyphen) since
    # child loggers are named "<name>.<module>" via __name__.
    names: list[str] = Field(default_factory=lambda: ["rag_api"])


class McpSettings(BaseModel):
    enabled: bool = True
    transport: str = "stdio"   # stdio | sse | streamable-http
    host: str = "0.0.0.0"
    port: int = 8001


class TracingSettings(BaseModel):
    enabled: bool = False
    langfuse_baseurl: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    service_name: str = "rag-api"


class SimHashSettings(BaseModel):
    """Stage1 — SimHash near-duplicate detection."""

    ngram: int = 3
    num_bands: int = 4
    simhash_bits: int = 64
    hamming_identical_threshold: int = 3
    hamming_similar_threshold: int = 10


class MinHashSettings(BaseModel):
    """Stage2 — MinHash / title fuzzy-match detection (runs only when Stage1 finds no candidate)."""

    jaccard_threshold: float = 0.65
    title_fuzzy_threshold: float = 0.85
    title_only_min_jaccard_floor: float = 0.25
    # Kiwi user word dictionary (relative to project root; empty = no user dict)
    user_words_path: str = ""


class ChunkCompareSettings(BaseModel):
    """Stage3 — embedding-based chunk-level comparison (confirms Stage1/2 'similar' verdicts)."""

    chunk_match_threshold: float = 0.50
    body_identical_threshold: float = 0.95
    body_similar_threshold: float = 0.75
    compare_all_candidates: bool = False


class DedupSettings(BaseModel):
    enabled: bool = True
    simhash: SimHashSettings = Field(default_factory=SimHashSettings)
    minhash: MinHashSettings = Field(default_factory=MinHashSettings)
    chunk_compare: ChunkCompareSettings = Field(default_factory=ChunkCompareSettings)


class KBDefinition(BaseModel):
    id: str
    name: str = ""
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────
# 메인 설정
# ──────────────────────────────────────────────

_SETTINGS_PATH = Path(__file__).parents[3] / "settings.yaml"


class Settings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    dagster: DagsterSettings = Field(default_factory=DagsterSettings)
    s3: S3Settings = Field(default_factory=S3Settings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    dedup: DedupSettings = Field(default_factory=DedupSettings)
    queue_worker: QueueWorkerSettings = Field(default_factory=QueueWorkerSettings)
    queue_poll: QueuePollSettings = Field(default_factory=QueuePollSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    tracing: TracingSettings = Field(default_factory=TracingSettings)
    logging: LogSettings = Field(default_factory=LogSettings)
    knowledge_bases: list[KBDefinition] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path = _SETTINGS_PATH) -> Settings:
        if path.exists():
            with open(path) as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
        else:
            data = {}

        if api_key := os.environ.get("OPENAI_API_KEY"):
            data.setdefault("embedding", {})["openai_api_key"] = api_key
        if access_key := os.environ.get("S3_ACCESS_KEY"):
            data.setdefault("s3", {})["access_key"] = access_key
        if secret_key := os.environ.get("S3_SECRET_KEY"):
            data.setdefault("s3", {})["secret_key"] = secret_key
        if redis_password := os.environ.get("REDIS_PASSWORD"):
            data.setdefault("redis", {})["password"] = redis_password
        if postgres_user := os.environ.get("POSTGRES_USER"):
            data.setdefault("postgres", {})["user"] = postgres_user
        if postgres_password := os.environ.get("POSTGRES_PASSWORD"):
            data.setdefault("postgres", {})["password"] = postgres_password
        if reranker_api_key := os.environ.get("RERANKER_API_KEY"):
            data.setdefault("retrieval", {}).setdefault("rerank", {})["api_key"] = reranker_api_key
        if langfuse_public_key := os.environ.get("TRACING_LANGFUSE_PUBLIC_KEY"):
            data.setdefault("tracing", {})["langfuse_public_key"] = langfuse_public_key
        if langfuse_secret_key := os.environ.get("TRACING_LANGFUSE_SECRET_KEY"):
            data.setdefault("tracing", {})["langfuse_secret_key"] = langfuse_secret_key
        if production := os.environ.get("SERVER_PRODUCTION"):
            data.setdefault("server", {})["production"] = production.lower() in ("1", "true", "yes")
        if workers := os.environ.get("SERVER_WORKERS"):
            data.setdefault("server", {})["workers"] = int(workers)

        return cls.model_validate(data)


# 싱글턴
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_yaml()
    return _settings