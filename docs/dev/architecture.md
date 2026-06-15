# CNAP RAG Pipeline 아키텍처 v4.0

> LlamaIndex + Dagster 기반 RAG 시스템.
> FastAPI 업로드 → S3(MinIO) 저장 → MinIO Webhook → Redis 큐 → event_queue_sensor → 문서 단위 Dagster Run → Op 파이프라인(파싱/청킹/임베딩/저장) → Qdrant 저장.
> FastAPI로 KB 관리 및 검색 API 제공. Celery 없음.

---

## 변경 이력

| 버전 | 주요 변경 |
|------|-----------|
| v1.0 | 최초 작성 |
| v2.0 | 인증 누락, MinIO notification 설정, 문서 버전 관리, KB 삭제 순서, Celery 멱등성, 타임아웃, 헬스체크, 태스크ID, 검색 응답 스키마, Qdrant payload, Reranker fallback 보완 |
| v3.0 | **Celery 제거 → Dagster 도입**, LlamaIndex API 활용 명시, 문서 단위 Run 설계, DynamicOutput 제거(단순 선형), 프로젝트 구조 개편(pyproject.toml / src / tests), 로컬 main 실행 구조 추가 |
| v4.0 | MinIO Sensor → event_queue_sensor(Redis 큐 기반)로 전면 교체, minio_sensor 제거, _is_blocked_by_active_run 좀비 복구 통합, sparse 벡터 자체 TF 인코더로 변경, 아키텍처/설계 문서 분리 |

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
          S3            Qdrant           Redis
        (파일)        (벡터 DB)        (메타데이터)
```

### 핵심 설계 원칙

- **문서 단위 격리**: 문서 1개 = Dagster Run 1개. 문서별 독립 실패/재시도
- **다중 문서 병렬**: Sensor가 이벤트 N개 → `RunRequest` N개 반환 → Dagster가 `max_concurrent_runs` 내에서 병렬 실행
- **Celery 없음**: 태스크 큐, 워커 관리를 Dagster가 전담
- **LlamaIndex 활용**: 파싱(`SimpleDirectoryReader`), 청킹(`SentenceSplitter` 등), 임베딩(`OllamaEmbedding`, `OpenAIEmbedding`), 검색(`VectorStoreIndex`) API 사용
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
meta_op           (Redis)
    │  status → indexed, etag, chunk_count, indexed_at 갱신
```

### delete_job (문서 1개 단위)

```
event_queue_sensor (Redis rag:delete:queue)
    │  DELETE 이벤트 1건 → RunRequest 1개
    ↓
delete_chunks_op  (Qdrant)
    │  doc_key 필터로 청크 전체 삭제
    ↓
delete_meta_op    (Redis)
    │  doc:{kb_id}:{object_key} 키 삭제
```

---

## 3. 이벤트 처리 경로

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

---

## 4. 프로젝트 구조
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
│   ├── dagster_pipeline
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
