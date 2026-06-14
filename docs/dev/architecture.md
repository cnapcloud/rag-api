# CNAP RAG Pipeline 아키텍처 v3.0

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
                    ┌─────────────┐
                    │   FastAPI   │
                    └──────┬──────┘
                           │ 업로드 / 삭제
                           ↓
                    ┌─────────────┐
                    │  S3(MinIO)  │
                    └──────┬──────┘
                           │ 이벤트
                           ↓
                    ┌─────────────────┐
                    │ Webhook handler │
                    └──────┬──────────┘
                           │
                           ↓
              ┌────────────────────────┐
              │       Redis 큐          │
              └────────────┬───────────┘
                           │
               ┌───────────┴───────────┐
               ↓                       ↓
     event_queue_sensor         QueueWorker
        (Dagster)               (FastAPI 내장)
               └───────────┬───────────┘
                           ↓
              ┌────────────────────────┐
              │    인제스트 파이프라인      │
              │                        │
              │  validate → parse      │
              │  → chunk → embed       │
              │  → upsert → meta       │
              └────────────┬───────────┘
                           │
           ┌───────────────┼───────────────┐
           ↓               ↓               ↓
          S3            Qdrant           Redis
        (파일)        (벡터 DB)        (메타데이터)
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
    SentenceSplitter,            # recursive 전략
    SemanticSplitterNodeParser,  # semantic 전략
    HierarchicalNodeParser,      # document_aware 전략
)

parsers = {
    "recursive":      SentenceSplitter(chunk_size=1024, chunk_overlap=128),
    "semantic":       SemanticSplitterNodeParser(buffer_size=1, breakpoint_percentile_threshold=80),
    "document_aware": HierarchicalNodeParser.from_defaults(chunk_sizes=[2048, 1024, 512]),
}
```

### 임베딩 — LlamaIndex Embedding

```python
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

embeddings = {
    "ollama": OllamaEmbedding(model_name="bge-m3", base_url="http://ollama:11434"),
    "openai": OpenAIEmbedding(model="text-embedding-3-small", api_key=settings.embedding.openai_api_key),
}
```

### 검색 — VectorStoreIndex + QdrantVectorStore

```python
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.qdrant import QdrantVectorStore

vector_store = QdrantVectorStore(
    client=qdrant_client,
    collection_name=kb_id,
    enable_hybrid=True,
    fastembed_sparse_model="Qdrant/bm25",
)
index = VectorStoreIndex.from_vector_store(vector_store)
retriever = index.as_retriever(
    similarity_top_k=settings.retrieval.top_k,
    vector_store_query_mode="hybrid",
    alpha=settings.retrieval.alpha,
)
```

### Sparse 벡터 — FastEmbed BM25

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
    run_ingest_pipeline(kb_id=kb_id, file_path=file)

@app.command()
def serve():
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)

@app.command()
def search(kb_ids: list[str], query: str):
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
def run_ingest_pipeline(kb_id: str, file_path: Path):
    from src.pipeline.ops import validate, parse, chunk, embed, upsert, update_meta
    ctx = build_local_context(kb_id=kb_id, file_path=file_path)

    if not validate(ctx):
        print("Skipping: ETag unchanged")
        return

    documents = parse(ctx)
    nodes     = chunk(ctx, documents)
    vectors   = embed(ctx, nodes)
    upsert(ctx, nodes, vectors)
    update_meta(ctx)
    print(f"Done: {len(nodes)} chunks indexed")
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
│   ├── main.py                          # CLI 진입점 (typer)
│   ├── config/
│   │   └── settings.py                  # settings.yaml 로더 (pydantic-settings)
│   ├── pipeline/
│   │   ├── runner.py                    # 로컬 직접 실행용 래퍼
│   │   └── ops/
│   │       ├── validate.py              # ETag 중복·크기 검증
│   │       ├── parse.py                 # LlamaIndex SimpleDirectoryReader
│   │       ├── chunk.py                 # LlamaIndex NodeParser (3가지 전략)
│   │       ├── embed.py                 # LlamaIndex Embedding (asyncio 병렬)
│   │       ├── upsert.py                # Qdrant 기존 청크 삭제 + 삽입
│   │       └── meta.py                  # Redis 메타데이터 갱신
│   ├── dagster_pipeline/
│   │   ├── definitions.py               # Dagster Definitions (진입점)
│   │   ├── jobs/
│   │   │   ├── ingest_job.py
│   │   │   └── delete_job.py
│   │   ├── ops/
│   │   │   ├── ingest_ops.py            # @op 래퍼 (pipeline/ops 함수 호출)
│   │   │   └── delete_ops.py
│   │   ├── sensors/
│   │   │   ├── minio_sensor.py          # PUT/DELETE 이벤트 → RunRequest
│   │   │   └── upload_sensor.py
│   │   └── resources/
│   │       ├── minio_resource.py
│   │       ├── qdrant_resource.py
│   │       ├── redis_resource.py
│   │       └── embedding_resource.py
│   ├── rag/
│   │   ├── retriever.py                 # Hybrid Search
│   │   ├── reranker.py                  # Jina/Cohere/Voyage + Fallback
│   │   └── merger.py                    # 복수 KB 결과 RRF 머지
│   ├── api/
│   │   ├── app.py
│   │   └── routers/
│   │       ├── health.py
│   │       ├── kb.py
│   │       ├── docs.py
│   │       └── search.py
│   └── infra/
│       ├── minio.py
│       ├── qdrant.py
│       └── redis.py
│
└── tests/
    ├── conftest.py
    ├── unit/
    ├── integration/
    └── dagster/
```

---

## 6. Dagster 정의 구조

### definitions.py

```python
# src/dagster_pipeline/definitions.py
from dagster import Definitions
from src.dagster_pipeline.jobs.ingest_job import ingest_job
from src.dagster_pipeline.jobs.delete_job import delete_job
from src.dagster_pipeline.sensors.minio_sensor import minio_sensor
from src.dagster_pipeline.sensors.upload_sensor import upload_sensor

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

class IngestConfig(Config):
    kb_id: str
    object_key: str
    etag: str

@op(out={"valid": Out(is_required=False)})
def validate_op(context, config: IngestConfig):
    if validate(config.kb_id, config.object_key, config.etag):
        yield Output(config, output_name="valid")

@op
def parse_op(context, config_out: IngestConfig):
    return parse(config_out.kb_id, config_out.object_key)

@op
def chunk_op(context, documents):
    return chunk(documents)

@op
def embed_op(context, nodes):
    return embed(nodes)

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
                    "ops": {"validate_op": {"config": {
                        "kb_id": event.kb_id,
                        "object_key": event.object_key,
                        "etag": event.etag,
                    }}}
                },
                tags={"kb_id": event.kb_id},
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

## 7. 이벤트 감지 — MinIO → Redis 큐

Celery + `minio_listener.py` 대신 Dagster Sensor가 Redis 큐를 폴링한다.

```
MinIO 버킷 변경
    → MinIO Webhook → POST /internal/s3-event → Redis 큐 push
    → Dagster Sensor (poll_interval_sec 주기로 큐 소비)
    → RunRequest 생성 → Dagster Run 실행
```

더 빠른 반응이 필요한 경우에만 Webhook 연동 사용. 기본은 Sensor 폴링.

---

## 8. 문서 버전 관리 / 수정 처리

```
validate_op
    │
    ├─ Redis에서 기존 ETag 조회
    │       ├─ ETag 동일 → Output 미발행 → 파이프라인 종료
    │       └─ ETag 다름 또는 신규 → Output 발행 → 다음 Op 진행
    │
upsert_op
    ├─ Qdrant: 기존 청크 전체 삭제 (doc_key + kb_id 필터)
    └─ Qdrant: 신규 청크 배치 삽입
```

---

## 9. KB 삭제 데이터 정리 순서

```
DELETE /api/kb/{kb_id}
    │
    ├─ 1. Redis: kb:{kb_id}:meta → status = "deleting"
    ├─ 2. Qdrant: Collection {kb_id} drop
    ├─ 3. MinIO: {bucket}/{kb_id}/ 전체 삭제
    └─ 4. Redis: kb:{kb_id}:* 전체 삭제
```
