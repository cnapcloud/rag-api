# CNAP RAG Pipeline 아키텍처 v5.2

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
| v5.1 | 이벤트 처리 경로 상세화, 이벤트 라이프사이클 추가, QueueWorker zombie 복구 불가 명시, delay queue dedup 제거(_retry_id 도입) |
| v5.2 | 커넥터 섹션 추가 — 구조, 상태 처리 흐름, 커넥터/문서 상태 구분, 스케줄 등록 방식 |

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

## 2. 프로젝트 구조

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
│   ├── design
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

---

## 참조 문서

| 문서 | 내용 |
|------|------|
| [docs/design/flows.md](../design/flows.md) | Dagster 태스크 흐름, 검색 흐름, 이벤트 처리 경로, 커넥터 흐름 |
| [docs/design/internals.md](../design/internals.md) | 문서 상태, Redis 키 구조, Qdrant payload 스키마, HTTP 에러 코드 |
| [docs/design/mcp.md](../design/mcp.md) | MCP 서버 설계 |
| [docs/dev/data-schema.md](data-schema.md) | Postgres 테이블 스키마 |
