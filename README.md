# CNAP RAG API

LlamaIndex + Dagster 기반 문서 인제스트 및 하이브리드 검색 파이프라인.
S3(MinIO) 이벤트 → FastAPI 큐 → Dagster Op(파싱/청킹/임베딩/저장) → Qdrant.

---

## 빠른 시작

### 1. 의존성 설치

```bash
pip install -e ".[dev]"
```

### 2. MinIO 웹훅 설정

1. MinIO 콘솔 → **Buckets** → `rag-api` 버킷 생성
2. **Administrator > Notifications > Add Notification Target > Webhook**
   - Identifier: `rag-api`
   - Endpoint: `http://<host>:8000/internal/s3-event`
3. MinIO 재시작 후 `rag-api` 버킷 이벤트에 위 웹훅 등록

### 3. 서버 실행

```bash
# FastAPI (포트 8000)
# transport가 sse 또는 streamable-http이면 /mcp 엔드포인트도 함께 기동됨 (stdio 미지원)
PYTHONPATH=src python -m main serve --reload

# Dagster UI (포트 3000)
dagster dev -f src/dagster_pipeline/definitions.py

# MCP 서버 (stdio 기본, 포트 8001)
PYTHONPATH=src python -m main serve-mcp --transport streamable-http [--port 8001]
```

---

## 아키텍처 요약

```
MinIO Sensor (10s 폴링)
    │  PUT 이벤트 N건 → RunRequest N개
    ↓
validate_op → parse_op → chunk_op → embed_op → upsert_op → meta_op
                                                    │
                                              (Qdrant + Redis)
```

**핵심 원칙**
- 문서 1개 = Dagster Run 1개 (독립 실패/재시도)
- `max_concurrent_runs: 8` → Celery 대체
- `run_key` 중복 방지로 ETag 동일 문서 재처리 차단

---

## 프로젝트 구조

```
src/
├── main.py                         # CLI 진입점 (typer)
├── exceptions.py                   # 도메인 예외 계층 (RAGError 하위)
├── config/
│   └── settings.py                 # 설정 로더 (pydantic-settings)
├── pipeline/
│   ├── queue_worker.py             # S3 이벤트 큐 워커
│   └── ops/
│       ├── runner.py               # 로컬 직접 실행
│       ├── validate.py             # ETag 중복·크기 검증
│       ├── parse.py                # LlamaIndex SimpleDirectoryReader
│       ├── chunk.py                # NodeParser (3전략)
│       ├── embed.py                # Embedding (asyncio 병렬)
│       ├── upsert.py               # Qdrant upsert
│       └── meta.py                 # Redis 메타 갱신
├── dagster_pipeline/
│   ├── definitions.py              # Dagster 진입점
│   ├── jobs/
│   │   ├── ingest_job.py
│   │   └── delete_job.py
│   ├── ops/
│   │   ├── ingest_ops.py           # @op 래퍼 — 인제스트
│   │   └── delete_ops.py           # @op 래퍼 — 삭제
│   ├── sensors/
│   │   └── event_queue_sensor.py   # S3 이벤트 큐 센서
│   └── resources/
│       └── resources.py            # S3/Qdrant/Redis/Embedding 리소스
├── rag/
│   ├── retriever.py                # Hybrid Search
│   ├── merger.py                   # RRF 머지
│   └── reranker.py                 # Jina + fallback
├── api/
│   ├── app.py                      # FastAPI 팩토리 + 글로벌 핸들러
│   └── routers/
│       ├── health.py               # GET /health, /ready
│       ├── kb.py                   # KB CRUD
│       ├── docs.py                 # 문서 업로드·목록·삭제
│       ├── search.py               # POST /api/search
│       └── internal.py             # 내부 관리 엔드포인트
├── mcp_server/
│   ├── server.py                   # FastMCP 인스턴스 + 툴 등록
│   └── tools/
│       ├── search.py               # search 툴
│       ├── kb.py                   # list_knowledge_bases 툴
│       └── docs.py                 # get_document_status 툴
└── infra/
    ├── s3.py                       # S3(MinIO) 클라이언트
    ├── qdrant.py                   # Qdrant 클라이언트
    └── redis.py                    # ETag 캐시 + KB/문서 메타데이터
```

---

## API 목록

| Method | Path | 설명 |
|--------|------|------|
| GET | /health | Liveness |
| GET | /ready | Readiness (Qdrant/Redis/S3/Ollama) |
| GET | /api/kb | KB 목록 |
| POST | /api/kb | KB 생성 |
| DELETE | /api/kb/{kb_id} | KB 삭제 |
| GET | /api/kb/{kb_id}/docs | 문서 목록 |
| POST | /api/kb/{kb_id}/docs/upload | 단일 업로드 (202, job_id 반환) |
| POST | /api/kb/{kb_id}/docs/upload/batch | 배치 업로드 (202) |
| DELETE | /api/kb/{kb_id}/docs/{key} | 문서 삭제 (Qdrant + Redis + S3) |
| GET | /api/kb/{kb_id}/docs/{key}/status | 문서 인덱싱 상태 |
| POST | /api/kb/{kb_id}/reindex | KB 전체 재인덱스 (202) |
| POST | /api/kb/{kb_id}/docs/reindex | 문서 선택 재인덱스 (202) |
| POST | /api/search | Hybrid Search + Rerank |
| GET | /api/docs/status | 전체 문서 현황 |
| POST | /internal/s3-event | S3 이벤트 수신 → 인제스트 큐 enqueue |

---

## 테스트

```bash
# 단위 테스트
pytest tests/unit/ -v

# 통합 테스트 (인프라 필요)
pytest tests/integration/ -v

# Sensor 테스트
pytest tests/dagster/ -v

# 전체
pytest -v
```

---

## 설정 (config/settings.yaml)

주요 항목:

| 키 | 기본값 | 설명 |
|----|--------|------|
| `embedding.provider` | `ollama` | `ollama` / `openai` |
| `chunking.strategy` | `document_aware` | `recursive` / `semantic` / `document_aware` |
| `dagster.max_concurrent_runs` | `8` | 동시 처리 문서 수 |
| `retrieval.rerank.provider` | `jina` | Reranker API |
| `ingestion.max_file_size_mb` | `200` | 최대 파일 크기 |


---
# API 사용 가이드

## Knowledge Base 관리

**KB 생성**
```bash
curl -X POST http://localhost:8000/api/kb \
  -H "Content-Type: application/json" \
  -d '{"kb_id": "kb-01", "description": "상품 설명서"}'
```

**KB 목록 조회**
```bash
curl http://localhost:8000/api/kb | jq
```

**KB 삭제** (Qdrant 컬렉션 + MinIO 오브젝트 + Redis 메타 일괄 삭제)
```bash
curl -X DELETE http://localhost:8000/api/kb/kb-01
```

---

## 문서 업로드

**단일 파일**
```bash
export KB_ID="kb-01"
curl -X POST http://localhost:8000/api/kb/${KB_ID}/docs/upload \
  -F "file=@./data/ATD00002_2605.pdf"
```

**배치 (여러 파일)**
```bash
curl -X POST http://localhost:8000/api/kb/${KB_ID}/docs/upload/batch \
  -F "files=@file1.pdf" -F "files=@file2.pdf"
```

지원 포맷: `.pdf` `.md` `.docx` `.txt`
업로드 즉시 202를 반환하고, 인제스트는 백그라운드에서 처리됩니다.

**업로드 상태 확인**

`object_key`는 버킷 내 `{kb_id}/` 프리픽스를 제외한 나머지 경로입니다. API 업로드 시에는 파일명이 그대로 사용되며, 서브디렉토리가 있으면 경로 포함입니다.

```bash
curl http://localhost:8000/api/kb/{kb_id}/docs/{object_key}/status
# 파일명만 있는 경우
curl http://localhost:8000/api/kb/kb-01/docs/ATD00002_2605.pdf/status
# 서브디렉토리가 있는 경우
curl http://localhost:8000/api/kb/kb-01/docs/2024/q1/report.pdf/status
```

**강제 재인덱싱**

`force=true`를 사용하면 ETag 비교를 건너뛰고 무조건 재인덱싱합니다. 파일 내용이 동일해도 청킹·임베딩 설정이 바뀌었을 때 유용합니다.

```bash
# KB 전체 — ETag가 달라진 파일만
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex"

# KB 전체 — 모든 파일 강제 재인덱싱
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex?force=true"

# 단일 파일 강제 재인덱싱 (S3 재업로드 없이)
curl -X POST "http://localhost:8000/api/kb/kb-01/docs/reindex?key=ATD00002_2605.pdf&force=true"

# CLI — 로컬 파일을 S3에 재업로드한 뒤 강제 재인덱싱
python -m main ingest --kb-id kb-01 --file ./data/ATD00002_2605.pdf --force
```

---

## 인덱싱 현황 확인

**전체 KB 문서 현황 한 번에 조회**
```bash
curl http://localhost:8000/api/docs/status | jq
```

**KB별 문서 목록**
```bash
curl http://localhost:8000/api/kb/kb-01/docs | jq
```

**status 필터** (`pending` / `processing` / `indexed` / `failed`)
```bashcurl "http://localhost:8000/api/kb/kb-01/docs?status=indexed" 
| jq
curl "http://localhost:8000/api/kb/kb-01/docs?status=failed" | jq
```

**특정 문서 상태**
```bash
curl http://localhost:8000/api/kb/kb-01/docs/report.pdf/status | jq
```

---

## 검색

```bash
curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "TDF 구성상품", "kb_ids": ["kb-01"], "options": {"top_k": 5}}' | jq
```


---

## 알려진 이슈

| 항목 | 내용 |
|------|------|
| Qdrant 버전 체크 경고 | qdrant-client의 `get_server_version()`이 `verify=False`를 전달하지 않아 self-signed 인증서 환경에서 항상 `UserWarning: Failed to obtain server version` 발생. 동작에는 영향 없음. 해결책: Qdrant ingress에 공인 인증서 적용 |