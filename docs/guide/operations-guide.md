# Operations Guide

운영자 및 배포 담당자를 위한 운영 절차 가이드.
내부 동작 원리 및 데이터 구조는 [dev/design.md](../dev/design.md) 참고.

---

## 1. 컨테이너 구성

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

## 2. 센서 운영

### 상태 확인

```bash
docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml
```

### 수동 시작

방법 1 — Dagster UI (포트 3000)
```
Deployment > grpc:dagster-rag-api:4000 > Sensors > event_queue_sensor > Running 토글
```

방법 2 — CLI
```bash
docker exec dagster-daemon dagster sensor start event_queue_sensor -w /opt/dagster/workspace.yaml
```

### Redis 큐 상태 확인

```bash
redis-cli -h <host> -p 6379 -a <password>
LLEN rag:upload:queue
LLEN rag:delete:queue
ZCARD rag:upload:delay
ZCARD rag:delete:delay
```

---

## 3. Redis AOF 영속성 설정

Redis 기본 RDB 스냅샷 모드에서는 재시작 시 미처리 큐 이벤트가 유실될 수 있다.

`docker-compose.yml`에서 AOF 활성화:

```yaml
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD:-redis} --appendonly yes --appendfsync everysec
```

`appendfsync everysec`: 1초 단위 fsync — 성능과 내구성의 균형.

### 큐 유실 복구

AOF 없이 큐가 날아간 경우:

```bash
# 변경된 파일만 재큐잉 (ETag 비교)
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex"

# 모든 문서 강제 재인제스트
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex?force=true"
```

---

## 4. Dagster 로깅 설정

순수 함수(`pipeline/ops/`) 로그를 Dagster UI에 표시하려면 `dagster.yaml`에 등록:

```yaml
python_logs:
  python_log_level: INFO
  managed_python_loggers:
    - pipeline.ops
    - pipeline.queue_worker
    - rag
    - infra
```

---

## 5. MinIO Webhook 설정

파일 업로드/삭제 이벤트를 실시간으로 수신하는 구조:

```
MinIO (PUT/DELETE)
  → POST http://rag-api:8000/internal/s3-event
    → Redis 큐 → event_queue_sensor → ingest_job / delete_job
```

### docker-compose.yml 설정

```yaml
minio:
  environment:
    MINIO_NOTIFY_WEBHOOK_ENABLE_PRIMARY: "on"
    MINIO_NOTIFY_WEBHOOK_ENDPOINT_PRIMARY: "http://rag-api:8000/internal/s3-event"

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

```bash
# webhook 타겟 등록 확인
docker exec minio mc admin config get local notify_webhook

# 버킷 이벤트 구독 확인
docker exec minio mc event list local/rag-api

# 수동 재등록 (재배포 후 구독이 사라진 경우)
docker compose run --rm minio-init
```

| 항목 | 주의사항 |
|------|---------|
| `--event` 값 | `put,delete` 형식 (`s3:ObjectCreated:*` 형식 아님) |
| 엔드포인트 경로 | `/internal/s3-event` (prefix `/internal` 포함) |
| MinIO 재시작 시 | 버킷 구독은 `minio-init` 재실행 필요 |
| settings.yaml | Redis/MinIO 주소를 컨테이너 서비스명으로 설정 (`redis`, `minio`) |

---

## 6. 트러블슈팅 체크리스트

### 센서가 동작하지 않을 때

1. `docker ps`로 4개 컨테이너 모두 실행 중인지 확인
2. `docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml`로 센서 상태 확인
3. STOPPED이면 섹션 2의 수동 시작 방법으로 시작
4. `docker logs dagster-daemon --tail 50`에서 gRPC 연결 오류 여부 확인
5. Redis 큐에 이벤트가 실제로 쌓여 있는지 확인

### DagsterExecutionLoadInputError: No such file or directory (storage/)

**증상**
```
FileNotFoundError: /opt/dagster/dagster_home/storage/<run_id>/validate_op/valid_config
```

**해결** — `docker-compose.yml`에 `dagster-storage` named volume 마운트 확인:

```yaml
dagster-rag-api:
  volumes:
    - dagster-storage:/opt/dagster/dagster_home/storage

volumes:
  dagster-storage:
```

```bash
docker compose -f docker/docker-compose.yml up -d --force-recreate dagster-rag-api
```
