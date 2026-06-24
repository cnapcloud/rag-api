# CNAP RAG Pipeline 아키텍처 v5.0

> LlamaIndex + Dagster 기반 RAG 시스템.
> FastAPI 업로드 → S3(MinIO) 저장 → MinIO Webhook → Redis 큐 → 인제스트 파이프라인(파싱/청킹/임베딩) → Qdrant(벡터) + Postgres(메타데이터).
> FastAPI로 KB 관리 및 검색 API 제공. Redis는 큐 전용.

---

## 변경 이력

| 버전 | 주요 변경 |
|------|-----------|
| v1.0 | 최초 작성 |
| v2.0 | 인증 누락, MinIO notification 설정, 문서 버전 관리, KB 삭제 순서, Celery 멱등성, 타임아웃, 헬스체크, 태스크ID, 검색 응답 스키마, Qdrant payload, Reranker fallback 보완 |
| v3.0 | **Celery 제거 → Dagster 도입**, LlamaIndex API 활용 명시, 문서 단위 Run 설계, DynamicOutput 제거(단순 선형), 프로젝트 구조 개편(pyproject.toml / src / tests), 로컬 main 실행 구조 추가 |
| v4.0 | MinIO Sensor → event_queue_sensor(Redis 큐 기반)로 전면 교체, minio_sensor 제거, _is_blocked_by_active_run 좀비 복구 통합, sparse 벡터 자체 TF 인코더로 변경, 아키텍처/설계 문서 분리 |
| v5.0 | **Redis → Postgres 메타데이터 마이그레이션** (US-11), MCP 서버 추가, 검색 흐름 문서화 |

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
                    ┌──────────────────────────────┐
                    │ S3 Webhook (POST /internal/  │
                    │            s3-event)         │
                    └──────┬───────────────────────┘
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
          S3            Qdrant          Postgres
        (파일)        (벡터 DB)        (메타데이터)
```

### 핵심 설계 원칙

- **문서 단위 격리**: 문서 1개 = Dagster Run 1개. 문서별 독립 실패/재시도
- **다중 문서 병렬**: Sensor가 이벤트 N개 → `RunRequest` N개 반환 → Dagster가 `max_concurrent_runs` 내에서 병렬 실행
- **저장소 역할 분리**: Qdrant(벡터 청크), Postgres(KB/문서 메타데이터), Redis(인제스트·삭제 큐 전용)
- **이중 큐 소비 모드**: Dagster 환경에서는 `event_queue_sensor`가, Dagster 없는 환경에서는 `QueueWorker`(FastAPI 내장 asyncio 워커)가 동일한 Redis 큐를 소비
- **LlamaIndex 활용**: 파싱(`SimpleDirectoryReader`), 청킹(`SentenceSplitter` 등), 임베딩(`OllamaEmbedding`, `OpenAIEmbedding`) API 사용
- **로컬 우선**: `PYTHONPATH=src python -m main`으로 Dagster 없이 단일 문서 파이프라인 직접 실행 가능

---

## 2. Dagster 태스크 흐름

### ingest_job (문서 1개 단위)

```
event_queue_sensor (Redis rag:upload:queue)
    │  PUT 이벤트 1건 → RunRequest 1개 (max_per_poll 한도 내 배치 소비)
    ↓
validate_op
    │  ETag 중복 → 스킵 (status 복원 후 종료)
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
    │  Dense(bge-m3) + Sparse(자체 TF 인코더) 동시 생성
    ↓
upsert_op         (Qdrant Python Client)
    │  기존 청크 삭제 (doc_key 필터) → 신규 청크 배치 삽입
    ↓
meta_op           (Postgres)
    │  status → indexed, etag, chunk_count, updated_at 갱신
```

### delete_job (문서 1개 단위)

```
event_queue_sensor (Redis rag:delete:queue)
    │  DELETE 이벤트 1건 → RunRequest 1개
    ↓
delete_chunks_op  (Qdrant)
    │  doc_key 필터로 청크 전체 삭제
    ↓
delete_meta_op    (Postgres)
    │  documents 테이블에서 (kb_id, doc_source) 행 삭제
```

---

## 3. 검색(Search) 흐름

```
POST /api/search  (또는 MCP search 툴)
    │  {query, kb_ids, top_k, mode, min_score}
    ↓
retriever.search()   — kb_ids별 병렬 Qdrant 쿼리
    │  hybrid: dense(코사인) + sparse(BM25) 동시 검색
    │  similarity: dense 전용
    │  → SearchResult[] per KB
    ↓
merger.rrf_merge()   — multi-KB RRF 병합
    │  각 KB 결과를 순위 기반으로 단일 리스트로 합산
    ↓
reranker.rerank_async()   — Jina Reranker API
    │  fallback: Jina 실패 시 RRF 점수 그대로 사용
    ↓
SearchResponse  {results: [{text, score, rerank_score, kb_id, doc_key, page_num}]}
```

검색은 읽기 전용이며 Dagster와 무관하다. 실패한 KB는 로그만 남기고 빈 결과로 처리한다(단일 KB 오류가 전체 응답을 막지 않음).

---

## 4. 이벤트 처리 경로

```
[경로 A — 업로드 (주 경로)]
POST /api/kb/{id}/docs/upload (또는 /batch)
    → S3(MinIO) 저장
    → MinIO Webhook → POST /internal/s3-event
    → Redis 큐(rag:upload:queue) push

[경로 B — 재인덱스 / 수동 트리거]
POST /api/kb/{id}/docs/reindex (또는 /recover)
    → enqueue_upload_event() 직접 호출
    → Redis 큐 push

[공통]
Redis 큐
    → event_queue_sensor (poll_interval_sec 주기로 소비, max_per_poll 배치)
    → RunRequest 생성 → Dagster Run 실행
```

업로드 엔드포인트는 S3 저장만 수행하고 Redis enqueue는 MinIO Webhook이 담당한다.
재인덱스·복구 엔드포인트는 `enqueue_upload_event()`를 직접 호출해 큐에 push한다.

큐 소비 주체는 배포 환경에 따라 다르다.

| 환경 | 소비 주체 | 설정 |
|------|-----------|------|
| Dagster 있음 | `event_queue_sensor` | `ingestion.queue_worker_enabled: false` |
| Dagster 없음 | `QueueWorker` (FastAPI asyncio 백그라운드 태스크) | `ingestion.queue_worker_enabled: true` |

`QueueWorker`는 `rag:upload:queue`와 `rag:delete:queue`를 모두 소비하며, `asyncio.Semaphore`로 동시성을 제한한다.

---

## 5. MCP 서버

FastMCP 기반 LLM 툴 인터페이스. `search`, `list_knowledge_bases`, `get_document_status` 3개 툴을 노출한다.
FastAPI 프로세스에 embedded(`/mcp` 엔드포인트)되거나 `python -m main serve-mcp`로 독립 실행된다.

자세한 설계는 [mcp-design.md](mcp-design.md)를 참조.

---

## 6. 프로젝트 구조
(level 2까지만 표시)
```
rag-api
├── CLAUDE.md
├── Dockerfile
├── Dockerfile.dagster
├── Makefile
├── README.md
├── pyproject.toml
├── settings.yaml
├── settings.example.yaml
├── data
│   └── ATD00002_2605.pdf
├── docker
│   ├── dagster.yaml
│   ├── docker-compose.yml
│   ├── settings.yaml
│   └── workspace.yaml
├── docs
│   ├── dev
│   ├── guide
│   └── troubleshooting
├── src
│   ├── main.py
│   ├── exceptions.py
│   ├── api
│   ├── config
│   ├── defs
│   ├── infra
│   ├── mcp_server
│   ├── pipeline
│   └── rag
└── tests
    ├── conftest.py
    ├── dagster
    ├── integration
    └── unit
```
