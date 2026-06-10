# CNAP RAG Pipeline 요구사항 v3.0

> LlamaIndex + Dagster 기반 RAG 시스템.
> MinIO 문서를 Dagster Sensor가 실시간 감지 → 문서 단위 Run 트리거 → Op 파이프라인(파싱/청킹/임베딩/저장) → Qdrant 저장.
> FastAPI로 KB 관리 및 검색 API 제공. Celery 없음.

---

## 변경 이력

| 버전 | 주요 변경 |
|------|-----------|
| v1.0 | 최초 작성 |
| v2.0 | 인증 누락, MinIO notification 설정, 문서 버전 관리, KB 삭제 순서, Celery 멱등성, 타임아웃, 헬스체크, 태스크ID, 검색 응답 스키마, Qdrant payload, Reranker fallback 보완 |
| v3.0 | **Celery 제거 → Dagster 도입**, LlamaIndex API 활용 명시, 문서 단위 Run 설계, DynamicOutput 제거(단순 선형), 프로젝트 구조 개편(pyproject.toml / src / tests), 로컬 main 실행 구조 추가 |

---

## 1. 전체 아키텍처

### 개요도

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI 레이어                           │
│                                                             │
│  POST /api/kb/{id}/docs/upload   DELETE /api/kb/{id}/docs   │
│      (파일 업로드 → Object Storage)  (파일 삭제 → Object Storage)│
└──────────────────┬───────────────────────┬──────────────────┘
                   │                       │
                   ↓                       ↓
┌─────────────────────────────────────────────────────────────┐
│            S3-Compatible Object Storage                     │
│                     (파일 스토리지)                            │
└─────────────────────────────────────────────────────────────┘
                   │ s3:ObjectCreated / s3:ObjectRemoved
                   ↓
┌─────────────────────────────────────────────────────────────┐
│         POST /internal/s3-event  (webhook handler)          │
│                                                             │
│          → 항상 Redis 큐에 push                              │
│            rag:upload:queue / rag:delete:queue              │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ↓
┌─────────────────────────────────────────────────────────────┐
│                      Redis 큐 소비                           │
│                                                             │
│   dagster.enabled = true       dagster.enabled = false      │
│                                                             │
│   event_queue_sensor           QueueWorker                  │
│   (poll_interval_sec 주기)     (poll_interval_sec 주기)      │
│        │          │                  │           │          │
│        ↓          ↓                  ↓           ↓          │
│   ingest_job  delete_job       run_ingest   run_delete      │
│   (Dagster)   (Dagster)        (동시 실행 max_workers 제한)  │
└──────────────┬──────────────────────────────────────────────┘
               │ (ingest_job / run_ingest)
               ↓
┌─────────────────────────────────────────────────────────────┐
│              Dagster Op 파이프라인 (ingest_job)                │
│                                                             │
│  validate_op → parse_op → chunk_op → embed_op → upsert_op   │
│                                                    │        │
│                                               meta_op       │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│                      인프라 레이어                           │
│                                                             │
│  Object Storage   Redis          Qdrant          Ollama     │
│   (문서 저장)    (메타데이터)    (벡터 DB)       (임베딩)     │
└─────────────────────────────────────────────────────────────┘
```

### 핵심 설계 원칙

- **문서 단위 격리**: 문서 1개 = Dagster Run 1개. 문서별 독립 실패/재시도
- **다중 문서 병렬**: Sensor가 이벤트 N개 → `RunRequest` N개 반환 → Dagster가 `max_concurrent_runs` 내에서 병렬 실행
- **Celery 없음**: 태스크 큐, 워커 관리를 Dagster가 전담
- **LlamaIndex 활용**: 파싱(`SimpleDirectoryReader`), 청킹(`SentenceSplitter` 등), 임베딩(`OllamaEmbedding`, `OpenAIEmbedding`), 검색(`VectorStoreIndex`) API 사용
- **로컬 우선**: `python -m src.main`으로 Dagster 없이 단일 문서 파이프라인 직접 실행 가능

---

## 2. Dagster 태스크 흐름

### ingest_job (문서 1개 단위)

```
MinIO Sensor
    │  PUT 이벤트 1건 → RunRequest 1개
    ↓
validate_op
    │  ETag 중복 → Output 미발행 → 이후 Op 스킵 (자동 종료)
    │  파일 크기 초과 → 실패 처리
    ↓
parse_op          (LlamaIndex SimpleDirectoryReader)
    │  PDF/MD/Word → Document 객체
    ↓
chunk_op          (LlamaIndex SentenceSplitter / SemanticSplitter)
    │  Document → Node 리스트 (청크 N개)
    ↓
embed_op          (LlamaIndex OllamaEmbedding / OpenAIEmbedding)
    │  Node 리스트 → asyncio.gather로 배치 병렬 임베딩
    │  Dense(bge-m3) + Sparse(FastEmbed BM25) 동시 생성
    ↓
upsert_op         (Qdrant Python Client)
    │  기존 청크 삭제 (doc_key 필터) → 신규 청크 배치 삽입
    ↓
meta_op           (Redis)
    │  status → indexed, etag, chunk_count, indexed_at 갱신
```

### delete_job (문서 1개 단위)

```
Delete Sensor
    │  DELETE 이벤트 1건 → RunRequest 1개
    ↓
delete_chunks_op  (Qdrant)
    │  doc_key 필터로 청크 전체 삭제
    ↓
delete_meta_op    (Redis)
    │  doc:status:{kb_id}:{object_key} 키 삭제
```

### 다중 문서 병렬 처리

```python
# Sensor: 이벤트 N개 → RunRequest N개
@sensor(job=ingest_job)
def minio_sensor(context):
    events = poll_minio_events()          # PUT 이벤트 목록
    for event in events:
        yield RunRequest(
            run_key=f"{event.kb_id}:{event.object_key}:{event.etag}",
            run_config={
                "ops": {
                    "validate_op": {
                        "config": {
                            "kb_id": event.kb_id,
                            "object_key": event.object_key,
                            "etag": event.etag,
                        }
                    }
                }
            }
        )
# → Dagster가 max_concurrent_runs 범위 내에서 병렬 실행
```

### Dagster 설정 (dagster.yaml)

```yaml
run_coordinator:
  module: dagster.core.run_coordinator
  class: QueuedRunCoordinator
  config:
    max_concurrent_runs: 8          # 동시 처리 문서 수 (Celery concurrency 대체)
    tag_concurrency_limits:
      - key: "kb_id"
        limit: 4                    # KB별 동시 처리 상한
```

---

## 3. LlamaIndex 활용 범위

### 파싱 — SimpleDirectoryReader / 커스텀 리더

```python
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import PDFReader, MarkdownReader, DocxReader

# 파일 타입별 리더 자동 선택
reader = SimpleDirectoryReader(
    input_files=[local_path],
    file_extractor={
        ".pdf":  PDFReader(),
        ".md":   MarkdownReader(),
        ".docx": DocxReader(),
    }
)
documents = reader.load_data()
```

### 청킹 — NodeParser

```python
from llama_index.core.node_parser import (
    SentenceSplitter,        # recursive 전략
    SemanticSplitterNodeParser,  # semantic 전략
    HierarchicalNodeParser,  # document_aware 전략
)

# settings.yaml strategy에 따라 선택
parsers = {
    "recursive":       SentenceSplitter(chunk_size=1024, chunk_overlap=128),
    "semantic":        SemanticSplitterNodeParser(buffer_size=1, breakpoint_percentile_threshold=80),
    "document_aware":  HierarchicalNodeParser.from_defaults(chunk_sizes=[2048, 1024, 512]),
}
```

### 임베딩 — LlamaIndex Embedding

```python
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

# provider에 따라 선택
embeddings = {
    "ollama": OllamaEmbedding(
        model_name="bge-m3",
        base_url="http://ollama:11434",
    ),
    "openai": OpenAIEmbedding(
        model="text-embedding-3-small",
        api_key=settings.embedding.openai_api_key,
    ),
}
```

### 검색 — VectorStoreIndex + QdrantVectorStore

```python
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.qdrant import QdrantVectorStore

vector_store = QdrantVectorStore(
    client=qdrant_client,
    collection_name=kb_id,
    enable_hybrid=True,        # Dense + Sparse 동시 검색
    fastembed_sparse_model="Qdrant/bm25",
)
index = VectorStoreIndex.from_vector_store(vector_store)
retriever = index.as_retriever(
    similarity_top_k=settings.retrieval.top_k,
    vector_store_query_mode="hybrid",
    alpha=settings.retrieval.alpha,
)
```

### Sparse 벡터 — FastEmbed BM25 (LlamaIndex QdrantVectorStore 내장)

`enable_hybrid=True` + `fastembed_sparse_model="Qdrant/bm25"` 설정 시 LlamaIndex가 자동으로 sparse 벡터 생성 및 삽입을 처리한다. 별도 `SparseTextEmbedding` 호출 불필요.

---

## 4. 로컬 실행 구조

### 목적

Dagster 없이 `python -m src.main`으로 단일 문서 파이프라인을 직접 실행. 개발 중 빠른 단위 테스트 및 디버깅용.

### 실행 방법

```bash
# 단일 문서 파이프라인 직접 실행
python -m src.main ingest \
  --kb-id kb-cnap-platform \
  --file ./samples/keycloak-guide.pdf

# KB 생성
python -m src.main kb create --kb-id kb-cnap-platform --description "CNAP 플랫폼 문서"

# 검색 테스트
python -m src.main search \
  --kb-ids kb-cnap-platform \
  --query "Keycloak 설정 방법"

# Dagster UI 로컬 실행
dagster dev -f src/dagster_pipeline/definitions.py
# → http://localhost:3000
```

### main.py 구조

```python
# src/main.py
import typer
from src.pipeline.runner import run_ingest_pipeline
from src.api.app import create_app

app = typer.Typer()

@app.command()
def ingest(kb_id: str, file: Path):
    """Dagster 없이 단일 문서 파이프라인 직접 실행"""
    run_ingest_pipeline(kb_id=kb_id, file_path=file)

@app.command()
def serve():
    """FastAPI 서버 실행"""
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)

@app.command()
def search(kb_ids: list[str], query: str):
    """검색 직접 실행"""
    from src.rag.retriever import hybrid_search
    results = hybrid_search(query=query, kb_ids=kb_ids)
    for r in results:
        print(r)

if __name__ == "__main__":
    app()
```

### pipeline/runner.py — Op 함수 직접 호출

```python
# src/pipeline/runner.py
# Dagster Op과 동일한 함수를 직접 호출
# → Op 함수가 Dagster Context에 의존하지 않도록 순수 함수로 작성

def run_ingest_pipeline(kb_id: str, file_path: Path):
    from src.pipeline.ops import (
        validate, parse, chunk, embed, upsert, update_meta
    )
    ctx = build_local_context(kb_id=kb_id, file_path=file_path)

    if not validate(ctx):        # ETag 체크
        print("스킵: 이미 처리된 문서")
        return

    documents = parse(ctx)
    nodes     = chunk(ctx, documents)
    vectors   = embed(ctx, nodes)
    upsert(ctx, nodes, vectors)
    update_meta(ctx)
    print(f"완료: {len(nodes)}개 청크 인덱싱")
```

---

## 5. 프로젝트 구조

```
rag-api/
├── pyproject.toml
├── README.md
├── config/
│   └── settings.yaml
│
├── src/
│   ├── __init__.py
│   │
│   ├── main.py                          # CLI 진입점 (typer)
│   │                                    # python -m src.main ingest / serve / search
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py                  # settings.yaml 로더 (pydantic-settings)
│   │
│   ├── pipeline/                        # 핵심 파이프라인 로직
│   │   ├── __init__.py
│   │   ├── runner.py                    # 로컬 직접 실행용 래퍼
│   │   └── ops/
│   │       ├── __init__.py
│   │       ├── validate.py              # ETag 중복·크기 검증
│   │       ├── parse.py                 # LlamaIndex SimpleDirectoryReader
│   │       ├── chunk.py                 # LlamaIndex NodeParser (3가지 전략)
│   │       ├── embed.py                 # LlamaIndex Embedding (asyncio 병렬)
│   │       ├── upsert.py                # Qdrant 기존 청크 삭제 + 삽입
│   │       └── meta.py                  # Redis 메타데이터 갱신
│   │
│   ├── dagster_pipeline/                # Dagster 워크플로우 정의
│   │   ├── __init__.py
│   │   ├── definitions.py               # Dagster Definitions (진입점)
│   │   ├── jobs/
│   │   │   ├── ingest_job.py            # @job: validate→parse→chunk→embed→upsert→meta
│   │   │   └── delete_job.py            # @job: delete_chunks→delete_meta
│   │   ├── ops/
│   │   │   ├── ingest_ops.py            # @op 래퍼 (pipeline/ops 함수 호출)
│   │   │   └── delete_ops.py            # @op 래퍼
│   │   ├── sensors/
│   │   │   ├── minio_sensor.py          # PUT/DELETE 이벤트 → RunRequest
│   │   │   └── upload_sensor.py         # API 업로드 트리거
│   │   └── resources/
│   │       ├── minio_resource.py        # @resource MinIO 클라이언트
│   │       ├── qdrant_resource.py       # @resource Qdrant 클라이언트
│   │       ├── redis_resource.py        # @resource Redis 클라이언트
│   │       └── embedding_resource.py    # @resource LlamaIndex Embedding
│   │
│   ├── rag/                             # 검색 엔진
│   │   ├── __init__.py
│   │   ├── retriever.py                 # Hybrid Search (LlamaIndex VectorStoreIndex)
│   │   ├── reranker.py                  # Jina/Cohere/Voyage + Fallback
│   │   └── merger.py                    # 복수 KB 결과 RRF 머지
│   │
│   ├── api/                             # FastAPI
│   │   ├── __init__.py
│   │   ├── app.py                       # FastAPI 앱 팩토리 + startup
│   │   ├── dependencies.py              # 공통 의존성 (설정, 클라이언트)
│   │   └── routers/
│   │       ├── health.py                # GET /health, GET /ready
│   │       ├── kb.py                    # KB 관리
│   │       ├── docs.py                  # 문서 업로드 (Sensor 트리거)
│   │       └── search.py                # Hybrid Search + Rerank
│   │
│   └── infra/                           # 인프라 클라이언트 팩토리
│       ├── __init__.py
│       ├── minio.py
│       ├── qdrant.py
│       └── redis.py
│
└── tests/
    ├── __init__.py
    ├── conftest.py                       # pytest fixtures (Mock Resource)
    ├── unit/
    │   ├── test_validate.py
    │   ├── test_parse.py
    │   ├── test_chunk.py
    │   ├── test_embed.py
    │   └── test_search.py
    ├── integration/
    │   ├── test_ingest_pipeline.py       # execute_in_process 통합 테스트
    │   └── test_search_api.py
    └── dagster/
        └── test_sensors.py               # Sensor 단위 테스트
```

---

## 6. pyproject.toml

```toml
[project]
name = "rag-api"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    # LlamaIndex 코어
    "llama-index-core>=0.10.0",
    "llama-index-readers-file>=0.1.0",
    "llama-index-embeddings-ollama>=0.1.0",
    "llama-index-embeddings-openai>=0.1.0",
    "llama-index-vector-stores-qdrant>=0.2.0",

    # Dagster
    "dagster>=1.7.0",
    "dagster-webserver>=1.7.0",

    # FastAPI
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",

    # 인프라 클라이언트
    "minio>=7.2.0",
    "qdrant-client>=1.9.0",
    "redis>=5.0.0",
    "fastembed>=0.3.0",

    # 문서 파싱
    "pypdf>=4.0.0",
    "python-docx>=1.1.0",

    # 리랭커
    "httpx>=0.27.0",

    # 설정
    "pydantic-settings>=2.2.0",
    "pyyaml>=6.0",

    # CLI
    "typer>=0.12.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.14.0",
    "dagster-webserver>=1.7.0",
    "ruff>=0.4.0",
    "mypy>=1.9.0",
]

[project.scripts]
rag-api = "main:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]

[tool.hatch.build.targets.wheel.sources]
"src" = ""

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
src = ["src"]
line-length = 100
```

---

## 7. Dagster 정의 구조

### definitions.py (Dagster 진입점)

```python
# src/dagster_pipeline/definitions.py
from dagster import Definitions, EnvVar
from src.dagster_pipeline.jobs.ingest_job import ingest_job
from src.dagster_pipeline.jobs.delete_job import delete_job
from src.dagster_pipeline.sensors.minio_sensor import minio_sensor
from src.dagster_pipeline.sensors.upload_sensor import upload_sensor
from src.dagster_pipeline.resources import (
    minio_resource, qdrant_resource, redis_resource, embedding_resource
)

defs = Definitions(
    jobs=[ingest_job, delete_job],
    sensors=[minio_sensor, upload_sensor],
    resources={
        "minio":     minio_resource,
        "qdrant":    qdrant_resource,
        "redis":     redis_resource,
        "embedding": embedding_resource,
    },
)
```

### ingest_job.py

```python
# src/dagster_pipeline/jobs/ingest_job.py
from dagster import job, op, Out, Output, Config
from src.pipeline.ops import validate, parse, chunk, embed, upsert, update_meta

class IngestConfig(Config):
    kb_id: str
    object_key: str
    etag: str

@op(out={"valid": Out(is_required=False)})
def validate_op(context, config: IngestConfig):
    if validate(config.kb_id, config.object_key, config.etag):
        yield Output(config, output_name="valid")
    # Output 미발행 → 이후 Op 자동 스킵

@op
def parse_op(context, config_out: IngestConfig):
    return parse(config_out.kb_id, config_out.object_key)

@op
def chunk_op(context, documents):
    return chunk(documents)

@op
def embed_op(context, nodes):
    return embed(nodes)           # asyncio.gather 내부 병렬

@op
def upsert_op(context, config_out: IngestConfig, embedded_nodes):
    return upsert(config_out.kb_id, config_out.object_key, embedded_nodes)

@op
def meta_op(context, config_out: IngestConfig, upsert_result):
    update_meta(config_out.kb_id, config_out.object_key, upsert_result)

@job
def ingest_job():
    valid_config = validate_op()
    docs    = parse_op(valid_config)
    nodes   = chunk_op(docs)
    vectors = embed_op(nodes)
    result  = upsert_op(valid_config, vectors)
    meta_op(valid_config, result)
```

### minio_sensor.py

```python
# src/dagster_pipeline/sensors/minio_sensor.py
from dagster import sensor, RunRequest, SensorEvaluationContext
from src.infra.minio import poll_minio_events

@sensor(job=ingest_job, minimum_interval_seconds=10)
def minio_sensor(context: SensorEvaluationContext):
    events = poll_minio_events(context.cursor)

    for event in events:
        if event.event_type == "PUT":
            yield RunRequest(
                run_key=f"{event.kb_id}:{event.object_key}:{event.etag}",
                run_config={
                    "ops": {
                        "validate_op": {
                            "config": {
                                "kb_id": event.kb_id,
                                "object_key": event.object_key,
                                "etag": event.etag,
                            }
                        }
                    }
                },
                tags={"kb_id": event.kb_id},   # KB별 동시성 제한에 활용
            )
        elif event.event_type == "DELETE":
            yield RunRequest(
                run_key=f"delete:{event.kb_id}:{event.object_key}",
                job_name="delete_job",
                run_config={...},
            )

    context.update_cursor(events[-1].cursor if events else context.cursor)
```

---

## 8. 로컬 테스트 방법

### 레벨 1 — Op 함수 직접 단위 테스트 (pytest)

```python
# tests/unit/test_chunk.py
from src.pipeline.ops.chunk import chunk
from llama_index.core import Document

def test_chunk_sentence_splitter():
    docs = [Document(text="A" * 3000)]
    nodes = chunk(docs, strategy="recursive", chunk_size=1024, chunk_overlap=128)
    assert len(nodes) > 1
    assert all(len(n.text) <= 1024 + 128 for n in nodes)
```

### 레벨 2 — Dagster 통합 테스트 (execute_in_process)

```python
# tests/integration/test_ingest_pipeline.py
from dagster import execute_in_process
from src.dagster_pipeline.jobs.ingest_job import ingest_job

def test_ingest_job(mock_resources):
    result = execute_in_process(
        ingest_job,
        run_config={
            "ops": {
                "validate_op": {
                    "config": {
                        "kb_id": "kb-test",
                        "object_key": "pdf/test.pdf",
                        "etag": "abc123",
                    }
                }
            }
        },
        resources=mock_resources,   # Mock MinIO/Qdrant/Redis
    )
    assert result.success
```

### 레벨 3 — Dagster UI 로컬 실행

```bash
# 의존성 설치
pip install -e ".[dev]"

# Dagster UI 실행 (포트 3000)
dagster dev -f src/dagster_pipeline/definitions.py

# CLI로 단일 문서 직접 실행
python -m src.main ingest --kb-id kb-test --file ./samples/test.pdf
```

---

## 9. KB 관리

### 생성 방법

- `settings.yaml` 정의 → FastAPI startup 시 자동 생성 (이미 있으면 스킵)
- `POST /api/kb` API로 런타임 추가

### KB별 독립 관리 대상

- MinIO 경로: `rag-api/{kb_id}/`
- Qdrant Collection: `{kb_id}` (Dense + Sparse 벡터)
- Redis 메타데이터: `kb:{kb_id}:*`

---

## 10. MinIO 이벤트 감지

### Dagster Sensor 방식 (Celery 대체)

Celery + `minio_listener.py` 대신 Dagster Sensor가 MinIO를 폴링한다.

```
MinIO 버킷 변경
    → Dagster Sensor (10초 주기 폴링 또는 MinIO Webhook)
    → RunRequest 생성
    → Dagster Run 실행
```

### MinIO Webhook 연동 (선택)

더 빠른 반응이 필요한 경우, MinIO Webhook → FastAPI 엔드포인트 → Redis 큐 → Sensor가 Redis 큐를 폴링하는 방식으로 구성 가능.

```yaml
# settings.yaml
minio:
  endpoint: "http://minio:9000"
  access_key: ""
  secret_key: ""
  bucket: "rag-api"
  poll_interval_sec: 10           # Sensor 폴링 주기
```

---

## 11. 문서 버전 관리 / 수정 처리

### PUT 이벤트 처리 플로우

```
validate_op
    │
    ├─ Redis에서 기존 ETag 조회
    │       ├─ ETag 동일 → Output 미발행 → 파이프라인 종료
    │       └─ ETag 다름 또는 신규 → Output 발행 → 다음 Op 진행
    │
upsert_op
    │
    ├─ Qdrant: 기존 청크 전체 삭제 (doc_key + kb_id 필터)
    └─ Qdrant: 신규 청크 배치 삽입
```

---

## 12. KB 삭제 데이터 정리 순서

```
DELETE /api/kb/{kb_id}
    │
    ├─ 1. Redis: kb:{kb_id}:meta → status = "deleting"
    ├─ 2. Qdrant: Collection {kb_id} drop
    ├─ 3. MinIO: {bucket}/{kb_id}/ 전체 삭제
    └─ 4. Redis: kb:{kb_id}:* 전체 삭제
```

---

## 13. 대용량 파일 처리

```yaml
# settings.yaml
ingestion:
  max_file_size_mb: 200
  dagster_run_timeout_sec: 600     # Run 전체 타임아웃 (dagster.yaml op_timeout 대체)
```

Dagster Op 타임아웃은 `dagster.yaml`의 `run_monitoring.run_timeout_seconds`로 설정.

---

## 14. 검색

### Hybrid Search 흐름

```
POST /api/search
    │
    ├─ KB별 LlamaIndex VectorStoreIndex 병렬 검색 (top_k 후보)
    │       Dense (bge-m3) + Sparse (BM25) → Qdrant Hybrid
    │
    ├─ 복수 KB 결과 RRF 머지 (score normalization)
    │
    ├─ Reranker API (Jina/Cohere/Voyage)
    │       실패 시 → RRF 스코어 순 top_n Fallback
    │
    └─ top_n 최종 반환
```

### 검색 요청/응답 스키마

```json
POST /api/search
{
    "query": "Keycloak 설정 방법",
    "kb_ids": ["kb-cnap-platform", "kb-kubernetes"],
    "options": {
        "mode": "hybrid",
        "top_k": 10,
        "alpha": 0.5,
        "rerank": { "enabled": true, "top_n": 3 }
    }
}

→ 200 OK
{
    "query": "Keycloak 설정 방법",
    "results": [
        {
            "chunk_id": "uuid",
            "kb_id": "kb-cnap-platform",
            "doc_key": "pdf/keycloak-guide.pdf",
            "doc_type": "pdf",
            "chunk_index": 3,
            "page_num": 2,
            "text": "Keycloak은 오픈소스 IAM...",
            "score": 0.923,
            "rerank_score": 0.871,
            "indexed_at": "2025-06-07T12:00:00Z"
        }
    ],
    "meta": {
        "total_candidates": 20,
        "returned": 3,
        "search_mode": "hybrid",
        "reranked": true,
        "rerank_provider": "jina",
        "rerank_fallback": false,
        "latency_ms": 142
    }
}
```

---

## 15. Qdrant Payload 스키마

```python
chunk_payload = {
    "kb_id":             "kb-cnap-platform",
    "doc_key":           "pdf/keycloak-guide.pdf",
    "doc_type":          "pdf",
    "chunk_index":       3,
    "page_num":          2,            # null 허용
    "total_chunks":      12,
    "text":              "Keycloak은 오픈소스 IAM...",
    "embedding_model":   "bge-m3",
    "embedding_provider":"ollama",
    "chunk_strategy":    "document_aware",
    "chunk_size":        1024,
    "chunk_overlap":     128,
    "indexed_at":        "2025-06-07T12:00:00Z",
}
```

---

## 16. 헬스체크 엔드포인트

```
GET /health   → 200 { "status": "ok" }                    # Liveness
GET /ready    → 200 { "status": "ready", "checks": {...} } # Readiness
              → 503 { "status": "not_ready", ... }
```

체크 대상: Qdrant, Redis, MinIO, Ollama(provider=ollama인 경우)

---

## 17. 업로드 API

```
POST /api/kb/{kb_id}/docs/upload
→ 202 { "object_key": "...", "run_id": "dagster-run-uuid", "status_url": "..." }

POST /api/kb/{kb_id}/docs/upload/batch
→ 202 { "results": [ { "filename": "...", "run_id": "...", "status_url": "..." }, ... ] }
```

`task_id` → `run_id` (Dagster Run ID로 대체)

---

## 18. API 전체 목록

```
# 헬스체크
GET    /health
GET    /ready

# KB 관리
GET    /api/kb
POST   /api/kb
DELETE /api/kb/{kb_id}

# 문서 관리
GET    /api/kb/{kb_id}/docs
POST   /api/kb/{kb_id}/docs/upload        → Dagster run_id 반환
POST   /api/kb/{kb_id}/docs/upload/batch  → run_id[] 반환
DELETE /api/kb/{kb_id}/docs/{key}
GET    /api/kb/{kb_id}/docs/{key}/status
GET    /api/kb/{kb_id}/docs?status=failed

# 검색
POST   /api/search

# 전체 현황
GET    /api/docs/status
```

---

## 19. Redis 키 구조

```
kb:list                             # KB 목록 (Set)
kb:{kb_id}:meta                     # KB 메타데이터 (Hash)

doc:status:{kb_id}:{object_key}     # 문서 상태 (Hash)
    → etag
    → status                        # processing | indexed | failed | skipped
    → run_id                        # Dagster Run ID (task_id 대체)
    → indexed_at
    → chunk_count
    → file_size
    → doc_type
    → embedding_model
    → error
```

---

## 20. 전체 설정 파일 (settings.yaml)

```yaml
minio:
  endpoint: "http://minio:9000"
  access_key: ""
  secret_key: ""
  bucket: "rag-api"
  poll_interval_sec: 10

redis:
  host: "redis"
  port: 6379

qdrant:
  host: "qdrant"
  port: 6333

dagster:
  max_concurrent_runs: 8
  run_timeout_sec: 600

ingestion:
  max_file_size_mb: 200

chunking:
  strategy: "document_aware"        # document_aware / recursive / semantic
  chunk_size: 1024
  chunk_overlap: 128
  semantic_threshold: 0.8

embedding:
  provider: "ollama"                # ollama / openai
  model: "bge-m3"
  ollama_url: "http://ollama:11434"
  openai_api_key: ""
  openai_model: "text-embedding-3-small"

retrieval:
  mode: "hybrid"
  top_k: 10
  alpha: 0.5
  merge_strategy: "rrf"
  rerank:
    enabled: true
    provider: "jina"
    api_key: ""
    model: "jina-reranker-v2-base-multilingual"
    top_n: 3
    timeout_sec: 5
    fallback_on_error: true

knowledge_bases:
  - id: "kb-cnap-platform"
    description: "CNAP 플랫폼 문서"
  - id: "kb-kubernetes"
    description: "Kubernetes 운영 가이드"
```