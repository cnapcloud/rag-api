# 기술 아키텍처

> 상위 개요: [README.md](README.md). 애플리케이션 계층 구조: [application.md](application.md).

---

## 1. 데이터 흐름

상세 흐름은 [runtime.md](runtime.md) 참조.

| 흐름 | 경로 |
|------|------|
| 인제스트 | API가 S3 저장 + Redis 큐 적재 → Sensor/Worker → Pipeline → Qdrant + Postgres |
| 삭제 | API → Redis → Sensor/Worker → Qdrant + S3 + Postgres |
| 검색 | API → RAG retriever → Qdrant → RRF merger → Jina reranker → 응답 |
| 커넥터 sync | API trigger 또는 Dagster Schedule → Connector가 S3 스테이징 + Redis 큐 적재 → Pipeline |

---

## 2. 배포 토폴로지

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

## 3. 보안

### API 인증·인가

현재 API 레벨 인증 없음. 내부 서비스(같은 네트워크)에서만 접근하는 것을 전제로 한다.
인증·인가가 필요한 배포는 rag-ent-api(OIDC + KB RBAC 확장 레이어)를 사용한다.

### 민감 정보 암호화

커넥터 설정의 인증 토큰(`auth_token_secret` 등)은 Fernet(AES-128-CBC) 대칭키로 암호화하여 Postgres에 저장한다.

- 복호화: `_dispatch_sync()` 호출 시점에만 수행
- API 응답: `"***"`으로 마스킹하여 반환
- 암호화 키: `settings.yaml`의 `security.fernet_key`로 관리

### 설정 보안

- 모든 민감값(API 키, DB 비밀번호 등)은 환경변수로 주입
- `settings.yaml`에 실제 값 하드코딩 금지. `settings.example.yaml`에 예시 값만 기재

---

## 4. 확장성 / 성능

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

## 5. 가용성 / 장애 복구

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

## 6. 헬스체크 / 모니터링

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
