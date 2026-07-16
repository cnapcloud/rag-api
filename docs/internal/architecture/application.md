# 애플리케이션 아키텍처

> 상위 개요: [README.md](README.md). 기술/인프라 관점: [technical.md](technical.md).

---

## 1. 레이어 구성

```
┌──────────────────────────────────────────────┐
│  CLI (Typer)           src/main.py           │
│  진입점 — serve / ingest / search / kb        │
├──────────────────────────────────────────────┤
│  API (FastAPI)         src/api/              │
│  라우터: health, kb, docs, search, connectors │
│  예외 핸들러, 미들웨어, 앱 팩토리               │
├──────────────────────────────────────────────┤
│  Pipeline (Dagster Ops) src/pipeline/step/    │
│  validate → parse → dedup → chunk → embed    │
│  → upsert → meta / delete                    │
│  순수 함수. Dagster 래퍼는 src/defs/에 분리     │
├──────────────────────────────────────────────┤
│  RAG                   src/rag/              │
│  retriever (Qdrant hybrid search)            │
│  merger (RRF)  reranker (Jina fallback)      │
├──────────────────────────────────────────────┤
│  Infra                 src/infra/            │
│  minio.py  redis.py  qdrant.py  postgres.py  │
│  s3.py (botocore)  connectors/               │
└──────────────────────────────────────────────┘
```

| 레이어 | 외부 의존 | 핵심 책임 |
|--------|-----------|-----------|
| CLI | FastAPI, pipeline | 커맨드 라우팅, 로컬 실행 |
| API | pipeline, rag, infra | HTTP 계약, 요청 검증, 에러 매핑 |
| Pipeline | infra | 문서 처리 순수 함수 |
| RAG | infra (Qdrant) | 검색·병합·리랭킹 |
| Infra | 외부 서비스 | 저장소 CRUD, 큐 조작 |

---

## 2. 컴포넌트 간 의존성

```
CLI
 └─ API (FastAPI app 임포트)
 └─ pipeline/runner.py (로컬 직접 실행)

API routers
 └─ pipeline/step/ (ingest, delete 트리거)
 └─ rag/ (search)
 └─ infra/ (kb/doc CRUD)

Dagster defs/
 └─ pipeline/step/ (op 래퍼)
 └─ infra/ (redis 큐 소비)

pipeline/step/
 └─ infra/ (S3, Qdrant, Postgres)
 └─ (외부: LlamaIndex, Jina)

rag/
 └─ infra/qdrant.py
 └─ (외부: Jina Reranker API)
```

상위 레이어는 하위 레이어만 참조한다. 역방향 참조 금지.

---

## 3. 예외 처리 전략

### 예외 계층

```
RAGError (base)
├── ConfigError           → HTTP 500
├── IngestValidationError → HTTP 422
├── NotFoundError         → HTTP 404
└── ConflictError         → HTTP 409
```

라이브러리 예외는 별도 래퍼 클래스 없이 `api/app.py` 핸들러에서 직접 HTTP 매핑:

| 예외 | HTTP |
|------|------|
| `botocore.exceptions.ClientError` | 502 |
| `redis.RedisError` | 503 |
| `psycopg.Error` | 503 |

### 레이어별 규칙

| 레이어 | 규칙 |
|--------|------|
| `infra/` | 라이브러리 예외를 그대로 전파. `ping()`만 예외적으로 swallow |
| `pipeline/step/` | 사용자 오류 → `IngestValidationError`, 설정 오류 → `ConfigError` |
| `api/routers/` | 비즈니스 404/409 → `NotFoundError` / `ConflictError`. 광범위한 `except Exception` 금지 |
| `api/app.py` | HTTP 상태코드 결정의 단일 지점 |

### Silent-fail 정책

| 상황 | 정책 |
|------|------|
| Qdrant/S3 삭제 실패 (hard delete 중) | warning 로그, 계속 진행 |
| 단일 KB 검색 실패 (multi-KB) | error 로그, 해당 KB 빈 결과 반환 |
| Jina reranker API 실패 | warning 로그, RRF 점수 fallback |
| 시작 시 인프라 초기화 실패 | warning 로그, 서버 계속 기동 |

---

## 4. 로깅 전략

### 기본 원칙

- 모든 모듈: `logger = logging.getLogger(__name__)` 사용
- 모든 로그 메시지는 영어로 작성
- 구조화된 키=값 형태 권장: `logger.info("Doc indexed: kb=%s doc_id=%s", kb_id, doc_id)`

### Dagster UI 노출

| 방식 | Dagster UI 노출 | 사용 위치 |
|------|----------------|-----------|
| `context.log.info()` | 항상 | Dagster op 래퍼 (`defs/ops/`) |
| `logging.getLogger(__name__)` | 기본 X | 순수 함수 (`pipeline/step/`) |
| `logging.getLogger(__name__)` + `managed_python_loggers` 설정 | O | `docker/dagster.yaml`에서 활성화 |

### 로그 레벨 기준

| 레벨 | 사용 상황 |
|------|-----------|
| `DEBUG` | 상세 내부 상태 (개발 시) |
| `INFO` | 주요 처리 단계 완료 |
| `WARNING` | silent-fail 상황, 예상 가능한 오류 |
| `ERROR` | 처리 실패, 예외 스택 트레이스 포함 |

---

## 5. 설정 관리

### 구조

```
settings.yaml           # 기본값 (git 추적)
settings.example.yaml   # 민감값 제외 예시 (git 추적)
환경변수                  # 런타임 오버라이드 (Pydantic Settings)
```

### 접근 패턴

```python
from rag_api.config.settings import get_settings

cfg = get_settings()  # 싱글턴, 최초 1회 로드 후 캐시
chunk_size = cfg.chunking.chunk_size
```

`get_settings()` 우회 및 값 하드코딩 금지.

### 주요 설정 키

| 키 | 설명 |
|----|------|
| `minio` | S3 엔드포인트, 버킷, 자격증명 |
| `redis` | 큐 호스트, 포트, DB 인덱스 |
| `qdrant` | 벡터 DB 호스트, 포트 |
| `postgres` | 메타데이터 DB DSN |
| `dagster` | Dagster gRPC 주소 |
| `ingestion` | 파일 크기 제한, 지원 확장자 |
| `chunking` | 전략(recursive/semantic), chunk_size, chunk_overlap |
| `embedding` | 모델 provider(ollama/openai), 모델명 |
| `retrieval` | top_k, alpha(dense/sparse 가중치) |
| `queue_worker` | enabled, poll_interval_sec, max_per_poll |
| `security` | fernet_key |

---

## 6. 프로젝트 구조

(level 2까지만 표시)

```
rag-api
├── CLAUDE.md
├── Dockerfile
├── Dockerfile.dagster
├── Makefile
├── pyproject.toml
├── settings.yaml
├── settings.example.yaml
├── docker
│   ├── dagster.yaml
│   ├── docker-compose.yml
│   └── workspace.yaml
├── docs
│   ├── guide
│   └── internal
├── src
│   ├── main.py
│   ├── exceptions.py
│   ├── api
│   ├── config
│   ├── connectors
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
