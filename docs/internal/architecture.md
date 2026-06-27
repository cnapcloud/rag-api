# RAG API 아키텍처

> LlamaIndex + Dagster 기반 문서 인제스트 및 하이브리드 검색 파이프라인.

---

## 변경 이력

| 버전 | 주요 변경 |
|------|-----------|
| v1.0 | 최초 작성 |
| v2.0 | 인증 누락, MinIO notification 설정, 문서 버전 관리, KB 삭제 순서, Celery 멱등성, 타임아웃, 헬스체크, 태스크ID, 검색 응답 스키마, Qdrant payload, Reranker fallback 보완 |
| v3.0 | Celery 제거 → Dagster 도입, LlamaIndex API 활용 명시, 문서 단위 Run 설계 |
| v4.0 | MinIO Sensor → event_queue_sensor(Redis 큐 기반)로 전면 교체, sparse 벡터 자체 TF 인코더 |
| v5.0 | Redis → Postgres 메타데이터 마이그레이션, MCP 서버 추가 |
| v5.1 | 이벤트 처리 경로 상세화, delay queue dedup 제거(_retry_id 도입) |
| v5.2 | 커넥터 섹션 추가 |
| v6.0 | 문서 전면 개편 — 레이어 구성, 예외처리, 로깅, 보안, 확장성, 가용성, 설정 관리 섹션 추가 |

---

## 1. 시스템 개요

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
- **이중 큐 소비 모드**: Dagster 환경은 `event_queue_sensor`, Dagster 없는 환경은 `QueueWorker`(FastAPI 내장 asyncio 워커)가 동일한 Redis 큐를 소비
- **순수 함수 Op**: 파이프라인 Op은 Dagster context 없이 동작하는 순수 함수. `runner.py`로 Dagster 없이도 직접 실행 가능

---

## 2. 레이어 구성

```
┌──────────────────────────────────────────────┐
│  CLI (Typer)           src/main.py           │
│  진입점 — serve / ingest / search / kb        │
├──────────────────────────────────────────────┤
│  API (FastAPI)         src/api/              │
│  라우터: health, kb, docs, search, internal   │
│  예외 핸들러, 미들웨어, 앱 팩토리               │
├──────────────────────────────────────────────┤
│  Pipeline (Dagster Ops) src/pipeline/ops/    │
│  validate → parse → chunk → embed            │
│  → upsert → meta / dedup / delete            │
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

## 3. 컴포넌트 간 의존성

```
CLI
 └─ API (FastAPI app 임포트)
 └─ pipeline/runner.py (로컬 직접 실행)

API routers
 └─ pipeline/ops/ (ingest, delete 트리거)
 └─ rag/ (search)
 └─ infra/ (kb/doc CRUD)

Dagster defs/
 └─ pipeline/ops/ (op 래퍼)
 └─ infra/ (redis 큐 소비)

pipeline/ops/
 └─ infra/ (S3, Qdrant, Postgres)
 └─ (외부: LlamaIndex, Jina)

rag/
 └─ infra/qdrant.py
 └─ (외부: Jina Reranker API)
```

상위 레이어는 하위 레이어만 참조한다. 역방향 참조 금지.

---

## 4. 데이터 흐름

상세 흐름은 [flows.md](design/flows.md) 참조.

| 흐름 | 경로 |
|------|------|
| 인제스트 | API → S3 → Webhook → Redis → Sensor/Worker → Pipeline → Qdrant + Postgres |
| 삭제 | API → Redis → Sensor/Worker → Qdrant + S3 + Postgres |
| 검색 | API → RAG retriever → Qdrant → RRF merger → Jina reranker → 응답 |
| 커넥터 sync | API trigger → Connector → S3 → Redis → Pipeline |

---

## 5. 배포 토폴로지

### 컨테이너 구성

| 컨테이너 | 이미지 | 역할 |
|----------|--------|------|
| `rag-api` | `Dockerfile` | FastAPI + QueueWorker |
| `dagster-webserver` | `Dockerfile.dagster` | Dagster UI |
| `dagster-daemon` | `Dockerfile.dagster` | Sensor 실행, Run 스케줄링 |
| `postgres` | `postgres:16` | 메타데이터 DB |
| `redis` | `redis:7` | 이벤트 큐 |
| `qdrant` | `qdrant/qdrant` | 벡터 DB |
| `minio` | `minio/minio` | S3 호환 오브젝트 스토리지 |
| `ollama` | `ollama/ollama` | 로컬 임베딩 모델 서버 |

### 실행 모드

| 모드 | 파이프라인 소비 | 설정 |
|------|----------------|------|
| Dagster 모드 (기본) | `event_queue_sensor` (daemon) | `queue_worker.enabled: false` |
| QueueWorker 모드 | FastAPI 내장 asyncio 워커 | `queue_worker.enabled: true` |
| 로컬 직접 실행 | `pipeline/runner.py` | `PYTHONPATH=src python -m main ingest` |

---

## 6. 예외 처리 전략

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
| `pipeline/ops/` | 사용자 오류 → `IngestValidationError`, 설정 오류 → `ConfigError` |
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

## 7. 로깅 전략

### 기본 원칙

- 모든 모듈: `logger = logging.getLogger(__name__)` 사용
- 모든 로그 메시지는 영어로 작성
- 구조화된 키=값 형태 권장: `logger.info("Doc indexed: kb=%s doc_id=%s", kb_id, doc_id)`

### Dagster UI 노출

| 방식 | Dagster UI 노출 | 사용 위치 |
|------|----------------|-----------|
| `context.log.info()` | 항상 | Dagster op 래퍼 (`defs/ops/`) |
| `logging.getLogger(__name__)` | 기본 X | 순수 함수 (`pipeline/ops/`) |
| `logging.getLogger(__name__)` + `managed_python_loggers` 설정 | O | `docker/dagster.yaml`에서 활성화 |

### 로그 레벨 기준

| 레벨 | 사용 상황 |
|------|-----------|
| `DEBUG` | 상세 내부 상태 (개발 시) |
| `INFO` | 주요 처리 단계 완료 |
| `WARNING` | silent-fail 상황, 예상 가능한 오류 |
| `ERROR` | 처리 실패, 예외 스택 트레이스 포함 |

---

## 8. 보안

### API 인증·인가

현재 API 레벨 인증 없음. 내부 서비스(같은 네트워크)에서만 접근하는 것을 전제로 한다.
`/internal/` 경로는 S3 Webhook 전용이며 외부 노출 금지.

### 민감 정보 암호화

커넥터 설정의 인증 토큰(`auth_token_secret` 등)은 Fernet(AES-128-CBC) 대칭키로 암호화하여 Postgres에 저장한다.

- 복호화: `_dispatch_sync()` 호출 시점에만 수행
- API 응답: `"***"`으로 마스킹하여 반환
- 암호화 키: `settings.yaml`의 `security.fernet_key`로 관리

### 설정 보안

- 모든 민감값(API 키, DB 비밀번호 등)은 환경변수로 주입
- `settings.yaml`에 실제 값 하드코딩 금지. `settings.example.yaml`에 예시 값만 기재

---

## 9. 확장성 / 성능

### 문서 병렬 처리

- Dagster `max_concurrent_runs` (기본 8): 동시에 인제스트할 수 있는 최대 문서 수
- `docker/dagster.yaml`의 `QueuedRunCoordinator.max_concurrent_runs`로 조정

### 임베딩 병렬화

- Dense + Sparse 임베딩을 `asyncio.gather`로 동시 실행
- 청크 배치를 한 번에 전송하여 모델 서버 왕복 최소화

### 검색 병렬화

- 복수 KB 검색 시 KB별 Qdrant 쿼리를 `asyncio.gather`로 병렬 실행
- 결과를 RRF로 단일 순위 리스트로 병합

### 큐 설계

- Redis List(main 큐) + Sorted Set(delay 큐) 조합
- 처리 중인 문서 이벤트는 delay 큐로 분리하여 main 큐 블로킹 방지
- `max_per_poll`: sensor 1회 tick에서 소비할 최대 이벤트 수 (설정으로 제한)

---

## 10. 가용성 / 장애 복구

### Zombie 문서 복구 (Dagster 모드)

서버 비정상 종료로 `running` 상태에 고착된 문서:

1. `event_queue_sensor`가 동일 문서 이벤트 수신
2. `run_id`로 Dagster에 실행 중인 Run 조회
3. Run이 존재하지 않으면 → `set_failed()` 후 새 Run 생성

QueueWorker 모드는 Dagster run_id 조회 불가 → zombie 자동 복구 없음. 수동 `/recover` API 사용.

### Reranker Fallback

Jina API 호출 실패 시 RRF 점수 순서를 그대로 반환 (`fallback_on_error: true`).

### 단일 KB 검색 장애 격리

multi-KB 검색에서 특정 KB Qdrant 쿼리 실패 시 해당 KB 결과만 빈 리스트로 처리. 나머지 KB 결과는 정상 반환.

### Soft Delete

`indexed` 상태 문서 삭제 시 Qdrant 청크와 dedup 밴드만 제거하고 DB row는 `deleted` 상태로 보존. 감사 추적 및 복원 가능성 유지.

---

## 11. 설정 관리

### 구조

```
settings.yaml           # 기본값 (git 추적)
settings.example.yaml   # 민감값 제외 예시 (git 추적)
환경변수                  # 런타임 오버라이드 (Pydantic Settings)
```

### 접근 패턴

```python
from config.settings import get_settings

cfg = get_settings()   # 싱글턴, 최초 1회 로드 후 캐시
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

## 12. 헬스체크 / 모니터링

### 엔드포인트

| 경로 | 유형 | 내용 |
|------|------|------|
| `GET /health` | Liveness | 프로세스 생존 여부. 항상 200 |
| `GET /ready` | Readiness | 모든 인프라 연결 확인. 하나라도 실패 시 503 |

### Readiness 체크 대상

Qdrant, Redis, Postgres, S3(MinIO), Ollama(embedding 서버)

각 infra 모듈의 `ping()` 함수를 호출. `ping()`은 내부적으로 예외를 swallow하고 `bool`을 반환한다.

### 모니터링 포인트

- Dagster UI(`localhost:3000`): Run 상태, Sensor tick, 실패 Run 로그
- 문서 상태 API(`GET /api/kb/{id}/docs`): 인제스트 현황 조회
- 로그: 컨테이너 stdout → 외부 로그 수집기 연동 가능

---

## 13. 프로젝트 구조

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

---

## 14. 참조 문서

| 문서 | 내용 |
|------|------|
| [design/flows.md](design/flows.md) | Dagster 태스크 흐름, 검색 흐름, 이벤트 처리 경로, 커넥터 흐름 |
| [design/backend-design.md](design/backend-design.md) | 문서 상태, Redis 키 구조, Qdrant payload 스키마, HTTP 에러 코드 |
| [design/mcp.md](design/mcp.md) | MCP 서버 설계 |
| [design/data-schema.md](design/data-schema.md) | Postgres 테이블 스키마 |
| [design/dedup.md](design/dedup.md) | 중복 감지 파이프라인 상세 설계 |
