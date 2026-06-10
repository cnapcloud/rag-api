# Operations Guide

## 인프라 설정 (settings.yaml)

### S3 (MinIO)

| 항목 | 값 |
|------|-----|
| endpoint | `https://minio-api.cnapcloud.com` |
| bucket | `rag-api` |
| region | `us-east-1` |
| insecure | `true` |
| access_key / secret_key | settings.yaml 참조 |

### Qdrant

| 항목 | 값 |
|------|-----|
| host | `192.168.0.184` |
| port | `6333` |
| insecure | `true` |

### Redis

| 항목 | 값 |
|------|-----|
| host | `192.168.0.183` |
| port | `6379` |
| db | `0` |
| password | settings.yaml 참조 |

### Redis 큐 구조

총 4개의 Redis 키가 인제스트 파이프라인에 사용된다.

| 키 | 타입 | 역할 |
|----|------|------|
| `rag:upload:queue` | List | PUT 이벤트 메인 큐. sensor가 `RPOP`으로 소비 |
| `rag:delete:queue` | List | DELETE 이벤트 메인 큐. sensor가 `RPOP`으로 소비 |
| `rag:upload:delay` | Sorted Set | 처리 중인 문서와 충돌한 PUT 이벤트 지연 보관. score = `ready_at` (Unix timestamp) |
| `rag:delete:delay` | Sorted Set | 처리 중인 문서와 충돌한 DELETE 이벤트 지연 보관. score = `ready_at` (Unix timestamp) |

**delay 큐 동작 원리**

sensor tick마다 먼저 delay 큐에서 `score <= now`인 항목을 꺼내 메인 큐로 이동(`ZRANGEBYSCORE` → `ZREM` → `LPUSH`)한다.
메인 큐 소비 중 해당 문서가 이미 처리 중(`try_set_processing` 실패)이면 `ready_at = now + processing_delay_sec`으로 delay Sorted Set에 재삽입한다.
`processing_delay_sec`는 `settings.yaml`의 `ingestion.processing_delay_sec`로 설정.

**delay 큐 상태 확인**
```bash
redis-cli -h <host> -p 6379 -a <password>
ZCARD rag:upload:delay
ZCARD rag:delete:delay
ZRANGE rag:upload:delay 0 -1 WITHSCORES
```

### Redis 큐 영속성

Redis는 기본적으로 RDB 스냅샷 모드로 동작한다. 스냅샷 주기(기본 60초 이상) 사이에 Redis가 재시작되면 4개 큐 키 모두 미처리 이벤트가 유실될 수 있다.

**docker-compose.yml에서 AOF 활성화** (영속성이 필요한 경우):
```yaml
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD:-redis} --appendonly yes --appendfsync everysec
```

`appendfsync everysec`: 1초 단위 fsync — 성능과 내구성의 균형.

**큐 유실 복구 방법** (AOF 없이 큐가 날아간 경우):
```bash
# ETag 비교 후 변경된 문서만 재큐잉
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex"

# 모든 문서 강제 재인제스트
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex?force=true"
```

`/reindex` 동작: MinIO에서 전체 문서 목록을 가져와 MinIO ETag vs Redis 캐시 ETag를 비교하고, 달라진 문서만 `rag:upload:queue`에 `LPUSH`한다. `force=true`이면 ETag 비교 없이 모두 큐잉한다.

---

### Embedding

| 항목 | 값 |
|------|-----|
| provider | `ollama` |
| model | `bge-m3` |
| vector_size | `1024` |
| ollama_url | `http://192.168.0.75:11434` |

### Ingestion

| 항목 | 값 | 설명 |
|------|-----|------|
| max_file_size_mb | `200` | 업로드 파일 크기 제한 |
| poll_interval_sec | `5` | Redis 큐 폴링 주기 |
| max_runs_per_tick | `5` | Dagster sensor 한 tick당 최대 RunRequest 수 |
| queue_worker_enabled | `false` | Dagster daemon 사용 시 false |

### Chunking

| 항목 | 값 |
|------|-----|
| strategy | `document_aware` |
| chunk_size | `1024` |
| chunk_overlap | `128` |

### Retrieval

| 항목 | 값 |
|------|-----|
| mode | `hybrid` |
| top_k | `10` |
| alpha | `0.5` |
| merge_strategy | `rrf` |
| rerank.enabled | `false` |

### Knowledge Bases

| ID | 설명 |
|----|------|
| `kb-01` | 지식베이스 01 |
| `kb-02` | 지식베이스 02 |

### MCP

| 항목 | 값 |
|------|-----|
| enabled | `true` |
| transport | `stdio` |
| port | `8001` |

**transport별 동작 방식**

| transport | 기동 방식 | 엔드포인트 |
|-----------|-----------|-----------|
| `stdio` | `serve-mcp` 단독 실행, 클라이언트가 subprocess로 띄움 | stdin/stdout |
| `sse` | `serve-mcp` 단독 또는 `serve`에 통합 | `http://host:port/mcp` |
| `streamable-http` | `serve-mcp` 단독 또는 `serve`에 통합 | `http://host:port/mcp` |

**기동 명령**

```bash
# stdio — 로컬 클라이언트(Claude Desktop 등)가 subprocess로 직접 실행
PYTHONPATH=src python -m main serve-mcp

# streamable-http — 독립 HTTP 서버로 기동 (포트 8001)
PYTHONPATH=src python -m main serve-mcp --transport streamable-http [--port 8001]

# streamable-http — FastAPI(serve)에 통합, 포트 8000의 /mcp 에 함께 노출
#   settings.yaml: mcp.enabled: true, mcp.transport: streamable-http
PYTHONPATH=src python -m main serve
```

**노출 툴**

| 툴 | 설명 |
|----|------|
| `search` | KB 하이브리드 검색 |
| `list_knowledge_bases` | KB 목록 조회 |
| `get_document_status` | 문서 인덱싱 상태 조회 |

**stdio 주의사항**

stdio transport는 stdin/stdout이 MCP 프로토콜 전용 채널이다. 서버 기동 시 자동으로 `sys.stdout → sys.stderr` 리다이렉트가 적용되므로 로그/출력이 프로토콜을 오염시키지 않는다.

---

## Dagster

### Sensor

#### event_queue_sensor

Redis 큐(`rag:upload:queue`, `rag:delete:queue`)를 polling하여 ingest_job / delete_job을 트리거하는 센서.

**동작 조건**

| 조건 | 설명 |
|------|------|
| `dagster-daemon` 컨테이너 실행 중 | 센서 tick은 daemon 프로세스가 담당 |
| `dagster-rag-api` gRPC 서버 실행 중 | daemon이 코드 서버에 연결 가능해야 tick 실행 |
| 센서 상태 RUNNING | STOPPED 상태이면 daemon이 완전히 무시 |

**주의: 센서 기본 상태**

Dagster 센서는 처음 등록 시 기본값이 STOPPED이다.
코드베이스에 `default_status=DefaultSensorStatus.RUNNING`을 설정해두었으므로 **새 환경(새 DB) 배포 시에는 자동으로 RUNNING** 상태로 시작된다.

`default_status`는 센서가 DB에 **처음 등록될 때만** 적용된다. 일단 저장된 상태는 재배포나 재시작으로 바뀌지 않는다.
STOPPED로 바뀌는 경우는 아래 두 가지뿐이다.

| 원인 | 설명 |
|------|------|
| 수동 stop | UI 토글 또는 `dagster sensor stop` CLI |
| DB 초기화 | PostgreSQL을 완전히 초기화하면 신규 등록으로 처리 → `default_status=RUNNING` 적용됨 |

STOPPED 상태가 된 경우 아래 방법 중 하나로 재시작한다.

**센서 수동 시작 방법**

방법 1 — Dagster UI (포트 3000)
```
Deployment > grpc:dagster-rag-api:4000 > Sensors > event_queue_sensor > Running 토글
```

방법 2 — CLI
```bash
docker exec dagster-daemon dagster sensor start event_queue_sensor -w /opt/dagster/workspace.yaml
```

**센서 상태 확인**
```bash
docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml
```

**Redis 큐 상태 확인**
```bash
redis-cli -h <host> -p 6379 -a <password>
LLEN rag:upload:queue
LLEN rag:delete:queue
LRANGE rag:upload:queue 0 -1
LRANGE rag:delete:queue 0 -1
```

---

### 컨테이너 구성

| 컨테이너 | 역할 | 포트 |
|----------|------|------|
| `dagster-postgresql` | Dagster 상태 저장소 (run/event/schedule) | 5432 |
| `dagster-rag-api` | gRPC 코드 서버 (definitions 로드) | 4000 |
| `dagster-webserver` | UI | 3000 |
| `dagster-daemon` | 센서/스케줄 실행 프로세스 | - |

**의존 관계**

```
dagster-postgresql (healthy)
  └─ dagster-rag-api (started)
       ├─ dagster-webserver
       └─ dagster-daemon
```

`dagster-rag-api`가 내려가면 daemon이 gRPC 연결 실패로 센서를 tick할 수 없다.
컨테이너 재시작 후 daemon 로그에서 아래 메시지가 나오면 정상 복구된 것이다.

```
Received LocationStateChangeEventType.LOCATION_UPDATED event for location grpc:dagster-rag-api:4000
```

---

### 트러블슈팅

#### DagsterExecutionLoadInputError: No such file or directory (storage/)

**증상**
```
FileNotFoundError: /opt/dagster/dagster_home/storage/<run_id>/validate_op/valid_config
```

**원인**

Dagster 기본 IO manager는 Op 간 중간 출력을 `$DAGSTER_HOME/storage/`에 파일로 저장한다.
`dagster-rag-api` 컨테이너에 해당 경로의 영구 볼륨이 없으면, 컨테이너 재시작 시 진행 중이던 Run의 중간 파일이 사라져 이후 Op이 실패한다.

**해결**

`docker-compose.yml`에 `dagster-storage` named volume이 마운트되어 있는지 확인:
```yaml
dagster-rag-api:
  volumes:
    - dagster-storage:/opt/dagster/dagster_home/storage

volumes:
  dagster-storage:
```

변경 후 컨테이너 재시작:
```bash
docker compose -f docker/docker-compose.yml up -d --force-recreate dagster-rag-api
```

---

#### 센서가 동작하지 않을 때 체크리스트

1. `docker ps`로 4개 컨테이너 모두 실행 중인지 확인
2. `docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml`로 센서 상태 확인
3. STOPPED이면 위의 수동 시작 방법으로 시작
4. `docker logs dagster-daemon --tail 50`에서 gRPC 연결 오류 여부 확인
5. Redis 큐에 이벤트가 실제로 쌓여 있는지 확인

---

### Dagster 로깅

#### 순수 함수 로그가 Dagster UI에 표시되지 않을 때

**원인**

`pipeline/ops/` 순수 함수들은 Python 표준 `logging.getLogger(__name__)`을 사용한다.
Dagster는 기본적으로 이 로거를 감시하지 않으므로, `context.log`를 통하지 않은 로그는 Dagster UI에 나타나지 않는다.
에러 트레이스백은 예외 자체를 `STEP_FAILURE` 이벤트로 캡처하기 때문에 예외적으로 보인다.

**해결**

`dagster.yaml`의 `python_logs.managed_python_loggers`에 감시할 로거 네임스페이스를 등록한다.

```yaml
python_logs:
  python_log_level: INFO
  managed_python_loggers:
    - pipeline.ops
    - pipeline.queue_worker
    - rag
    - infra
```

하위 로거(`pipeline.ops.embed`, `pipeline.ops.chunk` 등)는 상위 네임스페이스(`pipeline.ops`) 하나로 커버된다.

**로깅 방식 비교**

| 방식 | Dagster UI 노출 | 사용 위치 |
|------|----------------|-----------|
| `context.log.info()` | 항상 | Dagster op 래퍼(`dagster_pipeline/ops/`) |
| `logging.getLogger(__name__)` 기본 | X | 순수 함수(`pipeline/ops/`) |
| `logging.getLogger(__name__)` + `managed_python_loggers` | O | 순수 함수, 설정 후 |

---

## MinIO Webhook 설정

### 구조

MinIO 파일 업로드/삭제 이벤트를 polling 없이 실시간으로 수신하는 방식.

```
MinIO (PUT/DELETE)
  → POST http://rag-api:8000/internal/s3-event
    → Redis 큐 (rag:upload:queue / rag:delete:queue)
      → event_queue_sensor → ingest_job / delete_job
```

### docker-compose.yml 설정

`minio` 서비스에 webhook 타겟을 환경변수로 등록:

```yaml
minio:
  environment:
    MINIO_NOTIFY_WEBHOOK_ENABLE_PRIMARY: "on"
    MINIO_NOTIFY_WEBHOOK_ENDPOINT_PRIMARY: "http://rag-api:8000/internal/s3-event"
```

`minio-init` 컨테이너가 시작 시 버킷 이벤트 구독을 등록:

```yaml
minio-init:
  image: minio/mc:latest
  entrypoint: >
    /bin/sh -c "
    mc alias set local http://minio:9000 ...;
    mc mb --ignore-existing local/rag-api;
    mc mb --ignore-existing local/dagster-storage;
    mc event add local/rag-api arn:minio:sqs::PRIMARY:webhook --event put,delete --ignore-existing;
    "
  restart: "no"
```

### 설치 확인

**webhook 타겟 등록 확인**
```bash
docker exec minio mc alias set local http://localhost:9000 <user> <password>
docker exec minio mc admin config get local notify_webhook
```

정상 출력 예:
```
notify_webhook:PRIMARY
# MINIO_NOTIFY_WEBHOOK_ENABLE_PRIMARY=on
# MINIO_NOTIFY_WEBHOOK_ENDPOINT_PRIMARY=http://rag-api:8000/internal/s3-event
```

**버킷 이벤트 구독 확인**
```bash
docker exec minio mc event list local/rag-api
```

정상 출력 예:
```
arn:minio:sqs::PRIMARY:webhook   s3:ObjectCreated:*,s3:ObjectRemoved:*   Filter:
```

**수동 재등록** (재배포 후 구독이 사라진 경우)
```bash
docker compose run --rm minio-init
```

### 주의사항

| 항목 | 내용 |
|------|------|
| `mc event add --event` 값 | `put,delete` 형식 사용 (`s3:ObjectCreated:*` 형식 아님) |
| webhook 엔드포인트 경로 | `/internal/s3-event` (prefix `/internal` 포함) |
| MinIO 재시작 시 | webhook 타겟은 환경변수로 자동 복구, 버킷 구독은 `minio-init` 재실행 필요 |
| `dagster-rag-api` settings.yaml | Redis/MinIO 주소가 컨테이너 서비스명(`redis`, `minio`)으로 설정되어야 함 — 외부 IP 사용 시 sensor가 큐를 읽지 못함 |

---

## 알려진 경고 메시지

### onnxruntime CPUID warning (Mac + Docker)

```
dagster-rag-api | onnxruntime cpuid_info warning: Unknown CPU vendor. cpuinfo_vendor value: 0
```

**원인**

BM25 sparse 임베딩에 사용하는 `fastembed`가 내부적으로 `onnxruntime`으로 `Qdrant/bm25` 모델을 로컬에서 실행한다.
Docker on Mac은 Apple Hypervisor 위에 Linux VM으로 동작하므로 onnxruntime이 CPUID 명령을 실행해도 VM이 CPU 벤더 정보를 0으로 반환한다.
결과적으로 Metal / MPS / ANE 가속 없이 CPU 연산으로 폴백하며 이 경고가 출력된다.

**영향 없음** — 기능 동작에는 문제 없다. Linux 네이티브 서버에서는 CPUID가 정상 인식되어 경고가 나오지 않는다.

**fastembed 임베딩 흐름**

```
embed.py
  fastembed.SparseTextEmbedding("Qdrant/bm25")  <- onnxruntime이 컨테이너 안에서 실행
    -> sparse indices + values 계산 (클라이언트 측)
      -> Qdrant.upsert(sparse_vectors=...)       <- Qdrant는 저장만 담당
```

`"Qdrant/bm25"`는 Qdrant가 배포한 모델 이름이며, Qdrant 서버가 계산하는 서버 사이드 BM25와는 다르다.

---

### fastembed 모델 캐시 경로

fastembed의 기본 캐시 경로는 `tempfile.gettempdir()` 기반으로 결정된다. Docker 컨테이너에서는 `/tmp/fastembed_cache`가 되며, `/tmp`는 컨테이너 재시작마다 초기화되므로 **매번 모델을 재다운로드**한다.

**해결**

`FASTEMBED_CACHE_PATH` 환경변수로 캐시 경로를 `/tmp` 밖으로 지정하고, 이미지 빌드 시 모델을 미리 포함시킨다.

```dockerfile
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache

# 의존성 설치 후, 소스 복사 전에 실행 (레이어 캐시 활용)
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding('Qdrant/bm25')"
```

`Qdrant/bm25` 모델 크기는 약 104KB로 이미지에 포함시켜도 부담 없다.

캐시 경로 결정 로직 (`fastembed/common/utils.py`):
```python
default_cache_dir = os.path.join(tempfile.gettempdir(), "fastembed_cache")
cache_path = Path(os.getenv("FASTEMBED_CACHE_PATH", default_cache_dir))
```




