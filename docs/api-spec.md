# CNAP RAG Pipeline API 명세 v3.0

> API 엔드포인트, 요청/응답 스키마, 데이터 구조, 설정 파일 참조.
> 시스템 설계 및 흐름은 [architecture.md](architecture.md) 참고.

---

## 1. API 전체 목록

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
POST   /api/kb/{kb_id}/docs/upload
POST   /api/kb/{kb_id}/docs/upload/batch
DELETE /api/kb/{kb_id}/docs/{key}
GET    /api/kb/{kb_id}/docs/{key}/status
GET    /api/kb/{kb_id}/docs?status=failed

# 검색
POST   /api/search

# 전체 현황
GET    /api/docs/status
```

---

## 2. 헬스체크

```
GET /health   → 200 { "status": "ok" }                     # Liveness
GET /ready    → 200 { "status": "ready", "checks": {...} }  # Readiness
              → 503 { "status": "not_ready", ... }
```

체크 대상: Qdrant, Redis, MinIO, Ollama (provider=ollama인 경우)

---

## 3. KB 관리

### 생성 방법

- `settings.yaml`의 `knowledge_bases` 목록 → FastAPI startup 시 자동 생성 (이미 있으면 스킵)
- `POST /api/kb` API로 런타임 추가

### KB별 독립 관리 대상

| 레이어 | 경로/키 |
|--------|---------|
| MinIO  | `rag-api/{kb_id}/` |
| Qdrant | Collection `{kb_id}` (Dense + Sparse 벡터) |
| Redis  | `kb:{kb_id}:*` |

---

## 4. 문서 업로드 API

```
POST /api/kb/{kb_id}/docs/upload
→ 202 {
    "object_key": "keycloak-guide.pdf",
    "run_id": "dagster-run-uuid",
    "status_url": "/api/kb/{kb_id}/docs/keycloak-guide.pdf/status"
  }

POST /api/kb/{kb_id}/docs/upload/batch
→ 202 {
    "results": [
      { "filename": "doc1.pdf", "run_id": "...", "status_url": "..." },
      { "filename": "doc2.pdf", "run_id": "...", "status_url": "..." }
    ]
  }
```

---

## 5. 검색 API

### 요청

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
```

### 응답

```json
200 OK
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

### 검색 흐름

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

---

## 6. Qdrant Payload 스키마

```python
chunk_payload = {
    "kb_id":              "kb-cnap-platform",
    "doc_key":            "pdf/keycloak-guide.pdf",
    "doc_type":           "pdf",
    "chunk_index":        3,
    "page_num":           2,            # null 허용
    "total_chunks":       12,
    "text":               "Keycloak은 오픈소스 IAM...",
    "embedding_model":    "bge-m3",
    "embedding_provider": "ollama",
    "chunk_strategy":     "document_aware",
    "chunk_size":         1024,
    "chunk_overlap":      128,
    "indexed_at":         "2025-06-07T12:00:00Z",
}
```

---

## 7. Redis 키 구조

```
kb:list                             # KB 목록 (Set)
kb:{kb_id}:meta                     # KB 메타데이터 (Hash)

doc:{kb_id}:{object_key}            # 문서 상태 (Hash)
    → etag
    → status                        # running | indexed | failed | skipped
    → run_id                        # Dagster Run ID
    → indexed_at
    → chunk_count
    → file_size
    → doc_type
    → embedding_model
    → error

rag:upload:queue                    # 인제스트 이벤트 큐 (List)
rag:delete:queue                    # 삭제 이벤트 큐 (List)
```

---

## 8. 대용량 파일 처리

```yaml
# settings.yaml
ingestion:
  max_file_size_mb: 200
  dagster_run_timeout_sec: 600
```

Dagster Op 타임아웃은 `dagster.yaml`의 `run_monitoring.run_timeout_seconds`로 설정.

---

## 9. 로컬 테스트 방법

### 레벨 1 — Op 함수 직접 단위 테스트

```python
# tests/unit/test_chunk.py
from src.pipeline.ops.chunk import chunk
from llama_index.core import Document

def test_chunk_sentence_splitter():
    docs = [Document(text="A" * 3000)]
    nodes = chunk(docs, strategy="recursive", chunk_size=1024, chunk_overlap=128)
    assert len(nodes) > 1
```

### 레벨 2 — Dagster 통합 테스트

```python
# tests/integration/test_ingest_pipeline.py
from dagster import execute_in_process
from src.dagster_pipeline.jobs.ingest_job import ingest_job

def test_ingest_job(mock_resources):
    result = execute_in_process(
        ingest_job,
        run_config={
            "ops": {"validate_op": {"config": {
                "kb_id": "kb-test",
                "object_key": "pdf/test.pdf",
                "etag": "abc123",
            }}}
        },
        resources=mock_resources,
    )
    assert result.success
```

### 레벨 3 — Dagster UI 로컬 실행

```bash
pip install -e ".[dev]"
dagster dev -f src/dagster_pipeline/definitions.py
# → http://localhost:3000
```

---

## 10. 전체 설정 파일 (settings.yaml)

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

---

## 11. 의존성 (pyproject.toml)

```toml
[project]
name = "rag-api"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "llama-index-core>=0.10.0",
    "llama-index-readers-file>=0.1.0",
    "llama-index-embeddings-ollama>=0.1.0",
    "llama-index-embeddings-openai>=0.1.0",
    "llama-index-vector-stores-qdrant>=0.2.0",
    "dagster>=1.7.0",
    "dagster-webserver>=1.7.0",
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "minio>=7.2.0",
    "qdrant-client>=1.9.0",
    "redis>=5.0.0",
    "fastembed>=0.3.0",
    "pypdf>=4.0.0",
    "python-docx>=1.1.0",
    "httpx>=0.27.0",
    "pydantic-settings>=2.2.0",
    "pyyaml>=6.0",
    "typer>=0.12.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-mock>=3.14.0",
    "ruff>=0.4.0",
    "mypy>=1.9.0",
]

[project.scripts]
rag-api = "main:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
src = ["src"]
line-length = 100
```
