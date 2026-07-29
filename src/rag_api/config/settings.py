"""설정 로더 — config/settings.yaml + 환경변수 오버라이드."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal, get_args, get_origin

import yaml
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic.fields import FieldInfo

from rag_api.exceptions import IngestValidationError
from rag_api.pipeline.steps.chunk import ChunkStrategy

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
    # 하한은 0/음수 방지, 상한(1GB)은 임의 가드레일
    max_file_size_mb: int = Field(default=200, ge=1, le=1024, description="Max File Size (MB)")
    # 0 = 검사 비활성화, 상한은 "이 값 이상이면 사실상 모든 문서가 거부"되는 임의 가드레일
    min_content_chars: int = Field(default=200, ge=0, le=5000, description="Min Content Chars")
    # trafilatura extraction bias — see HTMLCleanReader (pipeline/steps/parser/html.py).
    # strict: 애매한 블록 제외 (짧고 확실한 본문만) / lenient: 애매한 블록 포함 (본문 손실 최소화,
    # 짧은 boilerplate 잔존 가능) / balanced: 중립.
    html_extraction_policy: Literal["strict", "lenient", "balanced"] = Field(
        default="lenient", description="HTML Extraction Policy",
    )
    # "module.path:register_func" 목록 — pipeline/steps/parser/registry.py가 지연 로드 시점에
    # 순서대로 import하여 각 register 함수를 호출한다. docs/internal/design/parser-registry.md 참고.
    # 배포 타임 모듈 존재 여부, KB별 분기 시 last-writer-wins 충돌 — kb-settings-override.md §5
    parser_plugins: list[str] = Field(
        default_factory=list, description="Parser Plugins", json_schema_extra={"override": False},
    )


class QueueWorkerSettings(BaseModel):
    enabled: bool = True
    max_workers: int = 4


class QueuePollSettings(BaseModel):
    poll_interval_sec: int = 5
    max_per_poll: int = 5
    retry_interval_sec: int = 10


class ChunkingSettings(BaseModel):
    strategy: ChunkStrategy = Field(default="recursive", description="Chunking Strategy")
    # strategy="recursive"/"semantic"이면 단일 int(기존과 동일). strategy="hierarchical"면
    # chunk_sizes 리스트(큰 것 -> 작은 것 순, 마지막 값이 leaf 크기) —
    # docs/internal/design/parent-child-chunking.md §6
    chunk_size: Annotated[int, Field(ge=64, le=8192)] | list[int] = Field(
        default=1024, description="Chunk Size",
    )
    chunk_overlap: int = Field(default=128, ge=0, le=8191, description="Chunk Overlap")
    semantic_threshold: float = Field(default=0.8, ge=0.0, le=1.0, description="Semantic Threshold")
    # 상한은 chunk_size 대비 상식적 가드레일
    min_chunk_chars: int = Field(default=30, ge=1, le=2000, description="Min Chunk Chars")
    # CodeSplitter의 실제 청크 크기 판단 기준(count_mode="char" 기본값) — chunk_lines/
    # chunk_lines_overlap는 설치된 llama-index-core 버전에서 생성자 인자로만 저장되고 실제
    # 분할 로직(_chunk_node)에서는 읽히지 않는 죽은 파라미터라 필드 자체를 없앴다.
    code_max_chars: int = Field(default=1500, ge=100, le=20000, description="Code Max Chars")

    @field_validator("chunk_size")
    @classmethod
    def _validate_chunk_size(cls, v: int | list[int]) -> int | list[int]:
        """list인 경우만 검증 — int 자체의 ge/le는 이미 Annotated[int, Field(...)]가 처리하지만,
        그건 int 분기에만 걸리고 list 항목에는 적용되지 않으므로 여기서 항목별로 같은 범위
        (64~8192)를 다시 확인한다(US-49). strategy와 chunk_size 모양이 안 맞는 조합(예:
        strategy="recursive"인데 리스트)은 여기서 막지 않는다 — 해당 전략의 파서가 런타임에
        즉시 실패한다(docs/internal/design/parent-child-chunking.md §6)."""
        if isinstance(v, list):
            if len(v) < 2:
                raise ValueError("chunk_size list must have at least 2 levels")
            if any(v[i] <= v[i + 1] for i in range(len(v) - 1)):
                raise ValueError("chunk_size list must be strictly descending")
            if any(item < 64 or item > 8192 for item in v):
                raise ValueError("chunk_size list items must be within 64-8192")
        return v

    @field_validator("chunk_overlap")
    @classmethod
    def _validate_chunk_overlap(cls, v: int, info: ValidationInfo) -> int:
        """pipeline/steps/chunk.py의 _build_hierarchical_parser가 이 값을 leaf(가장 작은)
        레벨에만 적용한다(root/mid는 overlap=0 — 임베딩/검색 대상이 아니라 겹쳐봐야 Postgres
        저장 용량만 늘어남, US-49 후속). 그래서 캡도 leaf(가장 작은) chunk_size 기준으로 건다 —
        지나치게 크면 SentenceSplitter가 크래시하지 않고 인접 leaf가 거의 통째로 겹치는 상태로
        조용히 색인된다(15% 캡 근거는 US-49 오픈 이슈 참고). chunk_size 자체가 이미 검증
        실패했으면 info.data에 값이 없으므로 건너뛴다(에러가 중복 보고되지 않게)."""
        chunk_size = info.data.get("chunk_size")
        if chunk_size is None:
            return v
        base = min(chunk_size) if isinstance(chunk_size, list) else chunk_size
        cap = base * 0.15
        if v > cap:
            raise ValueError(
                f"chunk_overlap ({v}) must not exceed 15% of chunk_size ({base}): max {cap:.0f}"
            )
        return v


class ProviderSettings(BaseModel):
    name: str = "ollama"               # ollama / openai — embedding, ingestion.image_captioning 공통
    ollama_url: str = "http://ollama:11434"
    openai_api_key: str = ""


class EmbeddingSettings(BaseModel):
    model: str = "bge-m3"              # provider에 맞는 모델명 (ollama: bge-m3 / openai: text-embedding-3-small)
    vector_size: int = 1024            # bge-m3=1024, text-embedding-3-small=1536, ada-002=1536


class RerankerSettings(BaseModel):
    # retrieval.rerank.*는 여러 KB를 한 요청으로 합쳐 검색할 때 병합된 결과 전체에 대해 정확히
    # 한 번만 적용되는 요청 단위 동작이라 "어느 KB의 설정을 쓸지"가 애초에 정의되지 않는다 —
    # KB별로 다르게 켜고 끌 수 있는 auto_merge(개별 KB 결과에 적용)와는 성격이 다르므로 전체
    # deny-list (docs/internal/design/kb-settings-override.md §5).
    enabled: bool = Field(
        default=True, description="Rerank Enabled", json_schema_extra={"override": False},
    )
    # internal = 자체 호스팅 Cohere-compatible rerank 서버 (base_url 필요)
    provider: Literal["jina", "internal"] = Field(
        default="jina", description="Rerank Provider", json_schema_extra={"override": False},
    )
    api_key: str = Field(default="", json_schema_extra={"override": False})
    model: str = Field(
        default="jina-reranker-v2-base-multilingual",
        description="Rerank Model",
        json_schema_extra={"override": False},
    )
    base_url: str = Field(
        default="", description="Rerank Base URL", json_schema_extra={"override": False},
    )  # provider=internal일 때만 사용 (예: http://reranker:8080/rerank)
    top_n: int = Field(
        default=3, description="Rerank Top N", json_schema_extra={"override": False},
    )
    timeout_sec: int = Field(
        default=5, description="Rerank Timeout (sec)", json_schema_extra={"override": False},
    )
    fallback_on_error: bool = Field(
        default=True, description="Fallback On Error", json_schema_extra={"override": False},
    )


class HybridSearchSettings(BaseModel):
    # alpha/rrf_k도 RerankerSettings와 같은 이유로 deny-list — mode="hybrid"에서 alpha는
    # KB별 검색 호출(_search_kb)에 값 자체는 들어가지만, rrf_k는 여러 KB의 결과를 합치는
    # merge 단계(rrf_merge)에서 요청당 한 번만 쓰인다. 두 필드를 분리해서 alpha만 여는 것도
    # 검토했으나(2026-07-29 논의), 값 하나가 요청 인자로 이미 들어오면 그게 우선이라는 현재
    # 정책과 일관되게 이번 범위에서는 hybrid 섹션 전체를 닫고 전역 설정 + 요청 인자로만
    # 제어한다.
    alpha: float = Field(
        default=0.5, description="Alpha (Hybrid)", json_schema_extra={"override": False},
    )
    rrf_k: int = Field(default=60, description="RRF K", json_schema_extra={"override": False})


class SimilaritySearchSettings(BaseModel):
    min_score: float = Field(
        default=0.0, description="Min Score", json_schema_extra={"override": False},
    )


class AutoMergeSettings(BaseModel):
    """Parent-child auto-merge — docs/internal/design/parent-child-chunking.md §5, §6.

    별도 스위치로 유지 — 청킹(저장, chunking.strategy="hierarchical")과 병합(검색)은 독립적으로
    껐다 켤 수 있어야 한다(예: 구조는 저장해두고 병합만 잠시 끄기). retrieval.* 중 KB별
    오버라이드가 열려 있는 건 이 섹션뿐이다 — _search_kb가 KB 단위로 직접 resolve_settings()를
    호출해 적용하는 유일한 retrieval 필드(kb-settings-override.md §5).
    """

    enabled: bool = Field(default=False, description="Auto Merge Enabled")
    merge_threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="Merge Threshold")


class RetrievalSettings(BaseModel):
    # mode/top_k도 rerank/hybrid와 동일한 이유(요청 단위로 한 번만 결정)로 deny-list.
    mode: Literal["hybrid", "similarity"] = Field(
        default="hybrid", description="Search Mode", json_schema_extra={"override": False},
    )
    top_k: int = Field(
        default=10, description="Top K", json_schema_extra={"override": False},
    )
    hybrid: HybridSearchSettings = Field(default_factory=HybridSearchSettings)
    similarity: SimilaritySearchSettings = Field(default_factory=SimilaritySearchSettings)
    rerank: RerankerSettings = Field(default_factory=RerankerSettings)
    auto_merge: AutoMergeSettings = Field(default_factory=AutoMergeSettings)


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

    # 기존 simhash_bands 지문과 계산 방식 불일치 위험 — kb-settings-override.md §5
    ngram: int = Field(default=3, description="N-gram Size", json_schema_extra={"override": False})
    num_bands: int = Field(
        default=4, description="Number of Bands", json_schema_extra={"override": False},
    )
    # hamming_*_threshold 상한의 근거값이기도 함
    simhash_bits: int = Field(
        default=64, description="SimHash Bits", json_schema_extra={"override": False},
    )
    # le=19는 저장 시점 sanity cap(근접 중복 판정 임계값이 20 이상이면 사실상 무의미) — 표시용
    # max는 이와 별개로 simhash_bits 기준 /settings/schema 응답 시점에 동적 계산(design doc §5).
    # cross-field: hamming_identical_threshold <= hamming_similar_threshold (design doc §3, 범위 밖)
    hamming_identical_threshold: int = Field(
        default=3, ge=0, le=19, description="Hamming Identical Threshold",
    )
    hamming_similar_threshold: int = Field(
        default=10, ge=0, le=19, description="Hamming Similar Threshold",
    )


class MinHashSettings(BaseModel):
    """Stage2 — MinHash / title fuzzy-match detection (runs only when Stage1 finds no candidate)."""

    jaccard_threshold: float = Field(default=0.65, ge=0.0, le=1.0, description="Jaccard Threshold")
    title_fuzzy_threshold: float = Field(
        default=0.85, ge=0.0, le=1.0, description="Title Fuzzy Threshold",
    )
    # jaccard_threshold와의 대소 관계는 cross-field 후보로 보이나 확정하지 않음 (design doc §2.1)
    title_only_min_jaccard_floor: float = Field(
        default=0.25, ge=0.0, le=1.0, description="Title-Only Min Jaccard Floor",
    )
    # Kiwi user word dictionary (relative to project root; empty = no user dict)
    # process-global Kiwi tokenizer singleton — kb-settings-override.md §5
    user_words_path: str = Field(
        default="", description="User Words Path", json_schema_extra={"override": False},
    )


class ChunkCompareSettings(BaseModel):
    """Stage3 — embedding-based chunk-level comparison (confirms Stage1/2 'similar' verdicts)."""

    chunk_match_threshold: float = Field(
        default=0.50, ge=0.0, le=1.0, description="Chunk Match Threshold",
    )
    # cross-field: body_similar_threshold <= body_identical_threshold (design doc §3, 범위 밖)
    body_identical_threshold: float = Field(
        default=0.95, ge=0.0, le=1.0, description="Body Identical Threshold",
    )
    body_similar_threshold: float = Field(
        default=0.75, ge=0.0, le=1.0, description="Body Similar Threshold",
    )
    compare_all_candidates: bool = Field(default=False, description="Compare All Candidates")


class DedupSettings(BaseModel):
    enabled: bool = Field(default=True, description="Dedup Enabled")
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

# /app/settings.yaml wins unconditionally when present — both rag-api standalone and any app
# vendoring it (e.g. rag-ent-api) use /app as their own container WORKDIR + settings.yaml
# location. Falls back to a path relative to this package's own install location (correct for
# local `uv run`/`rag-api serve`, where /app doesn't exist) otherwise. Without this, a vendoring
# app's settings.yaml is invisible to rag-api's own Settings.from_yaml() — it would resolve
# relative to wherever rag-api's source got installed instead (e.g. an editable path dependency
# mount), never the consuming app's own config.
_APP_SETTINGS_PATH = Path("/app/settings.yaml")
_SETTINGS_PATH = (
    _APP_SETTINGS_PATH if _APP_SETTINGS_PATH.exists() else Path(__file__).parents[3] / "settings.yaml"
)

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
    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    mcp: McpSettings = Field(default_factory=McpSettings)
    tracing: TracingSettings = Field(default_factory=TracingSettings)
    logging: LogSettings = Field(default_factory=LogSettings)
    knowledge_bases: list[KBDefinition] = Field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path = _SETTINGS_PATH) -> Settings:
        return cls.model_validate(_load_raw(path))


def _load_raw(path: Path = _SETTINGS_PATH) -> dict[str, Any]:
    """Load settings.yaml + apply env var overrides, returning the raw dict pre-validation.

    Split out from Settings.from_yaml so a vendoring app's extended Settings can reuse this
    (file parse + env overrides) once instead of duplicating it, then merge its own sections
    into the same dict before a single model_validate() call — see
    docs/internal/design/settings-composition.md.
    """
    if path.exists():
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    else:
        data = {}

    if api_key := os.environ.get("OPENAI_API_KEY"):
        data.setdefault("provider", {})["openai_api_key"] = api_key
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

    return data


# 싱글턴
_settings: Settings | None = None


def set_settings(instance: Settings) -> None:
    """Explicitly inject the process-wide Settings instance.

    A vendoring app calls this (from its own extended Settings.get_settings(), before any
    rag-api code runs) so get_settings() below returns that same instance instead of building
    its own default Settings from settings.yaml. See
    docs/internal/design/settings-composition.md.
    """
    global _settings
    _settings = instance


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_yaml()
    return _settings


# ──────────────────────────────────────────────
# KB별 설정 오버라이드 — docs/internal/design/kb-settings-override.md
# ──────────────────────────────────────────────

# 오버라이드 가능한 top-level 섹션. allow-list를 deny-list보다 먼저 적용 — provider/redis/postgres/
# qdrant 같은 인프라 자격증명 섹션은 이 목록에 없으므로 애초에 저장 시점에 거부된다.
OVERRIDABLE_SETTINGS_PREFIXES = ("ingestion.", "chunking.", "dedup.", "retrieval.")


def _override_allowed(field: FieldInfo) -> bool:
    """json_schema_extra={"override": False}로 명시된 필드만 배제, 그 외 기본 허용."""
    extra = field.json_schema_extra
    if not isinstance(extra, dict):
        return True
    return bool(extra.get("override", True))


def validate_override_key(settings_cls: type[BaseModel], dotted_key: str) -> None:
    """dot-key가 오버라이드 가능한 실제 필드 경로인지 확인한다.

    저장(PUT/PATCH) 시점에 반드시 호출해야 한다 — Settings는 model_config에서 extra를 지정하지
    않아 Pydantic 기본값(extra="ignore")을 쓰므로, resolve_settings()의 재검증 경로
    (type(base)(**merged))는 존재하지 않는 필드를 조용히 무시할 뿐 에러를 내지 않는다. 더 나쁜
    경우 스칼라 필드를 한 단계 더 파고드는 키(예: "dedup.enabled.foo")는 _apply_dotted_overrides가
    TypeError로 죽는다 — 그 KB는 이후 resolve_settings() 호출마다 예외가 나서 인제스트가 막힌다.

    필드 단위 배제(예: ingestion.parser_plugins)는 별도 deny-list가 아니라 필드 선언 옆
    json_schema_extra={"override": False}로 표시되어 있다 — 어차피 경로 존재 확인을 위해 하는
    model_fields 순회의 리프 필드에서 그 플래그까지 함께 확인한다(kb-settings-override-schema.md §4).
    """
    if not dotted_key.startswith(OVERRIDABLE_SETTINGS_PREFIXES):
        raise IngestValidationError(f"Settings key not overridable: {dotted_key!r}")

    node: Any = settings_cls
    field: FieldInfo | None = None
    for part in dotted_key.split("."):
        if not (isinstance(node, type) and issubclass(node, BaseModel)):
            raise IngestValidationError(f"Unknown settings key: {dotted_key!r}")
        field = node.model_fields.get(part)
        if field is None:
            raise IngestValidationError(f"Unknown settings key: {dotted_key!r}")
        node = field.annotation

    assert field is not None  # dotted_key is non-empty, so the loop ran at least once
    if not _override_allowed(field):
        raise IngestValidationError(f"Settings key not overridable: {dotted_key!r}")


def validate_override_values(base: Settings, overrides: dict[str, Any]) -> None:
    """override 값이 해당 필드의 Field(ge=/le=/Literal) 제약을 만족하는지 저장 시점에 확인한다.

    resolve_settings()도 type(base)(**merged)로 같은 재구성을 하지만 그건 인제스트 시점에야
    실행된다 — 값 자체가 잘못된 override(예: jaccard_threshold: 5.0)를 저장 시점에 걸러내려면
    같은 재구성을 PUT/PATCH 경로에서도 수행해야 한다. chunk_overlap-chunk_size 조합은
    ChunkingSettings._validate_chunk_overlap이 이 재구성 경로에서도 함께 걸린다(US-49). 그 외
    cross-field 제약(hamming_identical <= hamming_similar 등)은 여전히 검증 범위 밖(design doc
    §3).
    """
    merged = _apply_dotted_overrides(base.model_dump(), overrides)
    try:
        type(base)(**merged)
    except PydanticValidationError as e:
        raise IngestValidationError(f"Invalid settings override value: {e}") from e


def _apply_dotted_overrides(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """{"ingestion.image_captioning.enabled": False} 같은 dot-key를 base(중첩 dict)에 적용한다.

    base는 in-place로 수정되어 반환된다 — 호출부(resolve_settings)가 매번 새로 만든
    base.model_dump() 결과를 넘기므로 공유 상태를 건드리지 않는다.
    """
    for dotted_key, value in overrides.items():
        *path, leaf = dotted_key.split(".")
        node = base
        for part in path:
            node = node.setdefault(part, {})
        node[leaf] = value
    return base


def resolve_settings(kb_id: str | None) -> Settings:
    """전역 Settings에 KB override(flat dot-key)를 병합해 반환한다.

    kb_id가 None이거나 저장된 override가 없는 KB(대다수)는 전역 인스턴스를 그대로 반환한다 —
    불필요한 객체 생성이 없다. rag-ent-api처럼 Settings를 상속해 필드를 추가해도 type(base)로
    실제 서브클래스를 그대로 재구성하므로 이 함수는 그 필드들의 존재를 몰라도 된다.
    """
    base = get_settings()
    if kb_id is None:
        return base

    from rag_api.infra.postgres import get_kb_settings_overrides

    overrides = get_kb_settings_overrides(kb_id)
    if not overrides:
        return base
    merged = _apply_dotted_overrides(base.model_dump(), overrides)
    return type(base)(**merged)


def _int_range_from_union_annotation(annotation: Any) -> tuple[int | None, int | None] | None:
    """chunking.chunk_size(`Annotated[int, Field(ge=.., le=..)] | list[int]`)처럼 int 분기에
    ge/le가 붙은 Union annotation에서 그 범위를 꺼낸다. int 분기가 없으면 None."""
    for arg in get_args(annotation):
        if get_origin(arg) is Annotated:
            base, *extras = get_args(arg)
            if base is int:
                metadata = getattr(extras[0], "metadata", extras) if extras else []
                ge = next((m.ge for m in metadata if hasattr(m, "ge")), None)
                le = next((m.le for m in metadata if hasattr(m, "le")), None)
                return ge, le
    return None


# dedup.simhash.hamming_*_threshold의 진짜 상한은 정적 상수가 아니라 그 배포의 simhash_bits
# 값이다 — kb-settings-override-schema.md §5.
_DYNAMIC_MAX_HAMMING_KEYS = (
    "dedup.simhash.hamming_identical_threshold",
    "dedup.simhash.hamming_similar_threshold",
)


def describe_overridable_settings(current: Settings) -> dict[str, dict[str, Any]]:
    """ingestion/chunking/dedup 서브트리를 dot-key별 스키마 메타데이터로 직렬화한다.

    validate_override_key가 쓰는 것과 같은 model_fields 순회를 재사용한다
    (kb-settings-override-schema.md §5) — GET /kb/{kb_id}/settings/schema가 그대로 응답한다.

    top-level 섹션 클래스는 `type(current)`에서 가져온다(모듈의 `Settings`가 아니라) — rag-ent-api
    처럼 `Settings`를 상속해 `ingestion`을 확장 서브클래스로 재선언한 배포에서도 그 확장 필드
    (image_captioning 등)까지 순회되어야 한다. resolve_settings()가 이미 같은 이유로 `type(base)`를
    쓰는 것과 동일한 패턴.
    """
    schema: dict[str, dict[str, Any]] = {}

    def _walk(model_cls: type[BaseModel], prefix: str, group: str) -> None:
        for name, field in model_cls.model_fields.items():
            dotted_key = f"{prefix}.{name}"
            annotation = field.annotation

            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                _walk(annotation, dotted_key, name)
                continue

            union_int_range = _int_range_from_union_annotation(annotation)

            if get_origin(annotation) is Literal:
                field_type = "enum"
                enum_values: list[Any] | None = list(get_args(annotation))
            elif annotation is bool:
                field_type, enum_values = "bool", None
            elif annotation is int or union_int_range is not None:
                # union_int_range branch: e.g. chunking.chunk_size (int | list[int]) — reported
                # as "int" for backward compat, ge/le come from the Annotated[int, ...] union arm
                # since they aren't visible on field.metadata directly (parent-child-chunking.md §6)
                field_type, enum_values = "int", None
            elif annotation is float:
                field_type, enum_values = "float", None
            else:
                field_type, enum_values = "str", None

            min_value = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
            max_value = next((m.le for m in field.metadata if hasattr(m, "le")), None)
            if union_int_range is not None and min_value is None and max_value is None:
                min_value, max_value = union_int_range
            if dotted_key in _DYNAMIC_MAX_HAMMING_KEYS:
                max_value = current.dedup.simhash.simhash_bits

            schema[dotted_key] = {
                "type": field_type,
                "enum": enum_values,
                "default": field.get_default(call_default_factory=True),
                "overridable": _override_allowed(field),
                "min": min_value,
                "max": max_value,
                "description": field.description,
                "group": group,
            }

    for section in (p.rstrip(".") for p in OVERRIDABLE_SETTINGS_PREFIXES):
        section_cls = type(current).model_fields[section].annotation
        assert isinstance(section_cls, type) and issubclass(section_cls, BaseModel)
        _walk(section_cls, section, section)

    return schema