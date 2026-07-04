# Operations Guide

운영자 및 배포 담당자를 위한 절차 가이드.
내부 설계는 [dev/design.md](../dev/design.md), 추가 트러블슈팅은 [troubleshooting/dagster.md](../troubleshooting/dagster.md) 참고.

---

## 0. 빠른 참조

자주 쓰는 명령어 모음. 상세 설명은 각 섹션 참고.

```bash
# 전체 상태 확인
docker compose ps
curl -s http://localhost:8000/ready | jq

# API 생존 확인
curl -s http://localhost:8000/health

# Redis 큐 대기 수 확인
docker exec redis redis-cli -a <REDIS_PASSWORD> LLEN rag:upload:queue
docker exec redis redis-cli -a <REDIS_PASSWORD> LLEN rag:delete:queue

# Dagster 센서 상태
docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml

# 로그 확인
docker compose logs --tail=100 rag-api
docker compose logs --tail=100 dagster-daemon

# 수동 재인덱스 (변경분만)
curl -X POST http://localhost:8000/api/kb/kb-01/reindex

# 전체 재시작
docker compose down && docker compose up -d
```

---

## 1. 서비스 헬스체크

### 1-1. 컨테이너 상태 확인

```bash
docker compose ps
```

모든 컨테이너가 `healthy` 또는 `running`이어야 한다.
`minio-init`는 초기화 후 `Exited (0)`이 정상이다.

| 컨테이너 | 정상 상태 |
|---|---|
| `postgresql` | healthy |
| `redis` | healthy |
| `qdrant` | healthy |
| `minio` | healthy |
| `minio-init` | Exited (0) |
| `rag-api` | running |
| `rag-admin` | running |
| `dagster-rag-api` | running |
| `dagster-webserver` | running |
| `dagster-daemon` | running |

### 1-2. API 헬스체크

**생존 확인** (rag-api 프로세스만 확인)

```bash
curl -s http://localhost:8000/health
# {"status":"ok"}
```

**준비 확인** (Qdrant, Redis, Postgres, MinIO, 임베딩 모델 연결 모두 확인)

```bash
curl -s http://localhost:8000/ready | jq
```

모든 항목이 `true`여야 한다.

```json
{
  "status": "ready",
  "checks": {
    "qdrant": true,
    "redis": true,
    "postgres": true,
    "s3": true,
    "ollama": true
  }
}
```

`"status": "not_ready"`이면 `false`인 항목이 연결 실패다.

### 1-3. 문서 처리 상태 확인

인덱싱이 정상적으로 진행 중인지 확인한다.

```bash
# KB 내 문서 상태 목록
curl -s "http://localhost:8000/api/kb/kb-01/docs?page_size=20" | jq '.items[] | {doc_id, status, source}'

# 실패한 문서 확인
curl -s "http://localhost:8000/api/kb/kb-01/docs?status=failed" | jq '.items[] | {doc_id, source, last_error}'

# 처리 중인 문서 확인
curl -s "http://localhost:8000/api/kb/kb-01/docs?status=running" | jq '.total'
```

### 1-4. Dagster 센서 상태

```bash
docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml
```

`event_queue_sensor` 상태가 `RUNNING`이어야 한다.

Dagster UI(포트 3000)에서도 확인할 수 있다:
`Deployment > grpc:dagster-rag-api:4000 > Sensors`

---

## 2. 장애 대응 Runbook

### 2-1. 파일 업로드 후 문서 상태가 변하지 않을 때

순서대로 확인한다.

**Step 1 — rag-api가 enqueue했는지 확인**

```bash
docker compose logs --tail=50 rag-api | grep "enqueued\|enqueue"
```

`Upload event enqueued: doc_id=...` 로그가 없으면 API 호출 자체에 문제.
rag-api 로그에서 에러를 찾는다.

**Step 2 — Redis 큐에 이벤트가 있는지 확인**

```bash
docker exec redis redis-cli -a <REDIS_PASSWORD> LLEN rag:upload:queue
docker exec redis redis-cli -a <REDIS_PASSWORD> ZCARD rag:upload:delay
```

| 상태 | 의미 |
|------|------|
| 둘 다 0 | 센서가 이미 소비했거나 enqueue가 안 된 것 |
| `upload:queue` > 0 | 센서가 소비를 못 하고 있음 → Step 3 |
| `upload:delay` > 0 | 동일 doc이 실행 중(`running`/`deleting`)이어서 대기 중 → Step 3 후 zombie run 확인 |

**Step 3 — Dagster 센서 상태 확인**

```bash
docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml
docker compose logs --tail=100 dagster-daemon | grep -i "error\|warn\|sensor"
```

센서가 `STOPPED`면 → [2-2. Dagster 센서가 멈췄을 때] 진행.

**Step 4 — Dagster job 실행 기록 확인**

Dagster UI(포트 3000) > Runs 에서 최근 `ingest_job` 실행 결과를 확인한다.
실패한 run을 클릭하면 어느 op에서 에러가 났는지 볼 수 있다.

### 2-2. Dagster 센서가 멈췄을 때 (STOPPED)

`dagster-rag-api` gRPC 서버가 내려가면 센서가 자동 중지된다.

**Step 1 — dagster-rag-api 상태 확인**

```bash
docker compose ps dagster-rag-api
docker compose logs --tail=50 dagster-rag-api
```

**Step 2 — dagster-rag-api 재시작**

```bash
docker compose restart dagster-rag-api
```

재시작 후 daemon 로그에 아래 메시지가 나오면 연결 복구된 것이다.

```
Received LocationStateChangeEventType.LOCATION_UPDATED event for location grpc:dagster-rag-api:4000
```

**Step 3 — 재시작 전 실행 중이던 run 강제 종료**

`dagster-rag-api` 재시작 전에 실행 중이던 run은 프로세스가 사라졌지만 Dagster DB에 `STARTED` 상태로 남는다.
이 상태가 남아 있으면 센서가 해당 doc_id를 "실행 중"으로 보고 이벤트를 delay queue에 계속 밀어넣어 처리가 멈춘다.

Dagster UI(포트 3000) > Runs 에서 `STARTED` 상태인 run을 찾아 우측 상단 `Terminate` 버튼으로 강제 종료한다.

CLI로 일괄 처리:

```bash
# STARTED 상태 run ID 목록 조회
docker exec dagster-daemon dagster run list -w /opt/dagster/workspace.yaml --status STARTED

# 개별 강제 종료
docker exec dagster-daemon dagster run terminate <run_id> -w /opt/dagster/workspace.yaml
```

종료 후 해당 문서의 상태가 `failed`로 바뀐다. 이후 reindex로 재처리한다.

**Step 4 — 센서 수동 시작**

자동으로 `RUNNING`이 되지 않으면 수동으로 시작한다.

```bash
docker exec dagster-daemon dagster sensor start event_queue_sensor -w /opt/dagster/workspace.yaml
```

또는 Dagster UI > Sensors > `event_queue_sensor` > Running 토글.

### 2-3. Redis 큐가 계속 쌓일 때

**원인 1 — Dagster job이 계속 실패하는 경우**

```bash
docker compose logs --tail=200 dagster-daemon | grep -i "error\|failed"
```

Dagster UI > Runs 에서 실패한 run 상세 확인.

**원인 2 — 동일 문서가 `running` 상태에서 멈춘 경우 (zombie run)**

```bash
# 오래된 running 문서 확인 (Postgres)
docker exec postgresql psql -U rag-api -d rag-api -c \
  "SELECT doc_id, source, status, process_started_at FROM documents \
   WHERE status = 'running' AND process_started_at < NOW() - INTERVAL '30 minutes';"
```

zombie run이 있으면 해당 문서를 `failed`로 수동 초기화한다.

```bash
docker exec postgresql psql -U rag-api -d rag-api -c \
  "UPDATE documents SET status = 'failed', last_error = 'manually reset' \
   WHERE status = 'running' AND process_started_at < NOW() - INTERVAL '30 minutes';"
```

이후 수동 reindex로 재처리한다.

```bash
curl -X POST http://localhost:8000/api/kb/kb-01/docs/<doc_id>/reindex
```

### 2-4. rag-api가 기동하지 않을 때

인프라 4개가 모두 healthy인지 먼저 확인한다.

```bash
docker compose ps postgresql redis qdrant minio
```

healthy가 아닌 컨테이너가 있으면 해당 컨테이너 로그를 확인한다.

```bash
docker compose logs --tail=50 postgresql
```

모두 healthy인데도 기동 안 되면:

```bash
docker compose logs --tail=100 rag-api
```

`/ready` 엔드포인트 응답의 `false` 항목이 연결 실패 원인이다.

### 2-5. 커넥터 동기화가 진행되지 않을 때

**스케줄 기반 동기화**

Dagster UI(포트 3000) > Schedules 에서 해당 커넥터 스케줄(`connector_sync_<id>`)이 `RUNNING` 상태인지 확인한다.

`STOPPED`면 `dagster-rag-api`를 재시작한다 (스케줄은 재시작 시 자동 복구됨).

**수동 동기화**

```bash
curl -X POST http://localhost:8000/api/connectors/<connector_id>/sync
```

**동기화 중 abort**

```bash
curl -X POST http://localhost:8000/api/connectors/<connector_id>/sync/abort
```

---

## 3. 일상 운영

### 3-1. 로그 확인

```bash
# rag-api (업로드, 검색, API 에러)
docker compose logs --tail=100 -f rag-api

# Dagster daemon (센서, job 실행)
docker compose logs --tail=100 -f dagster-daemon

# Dagster gRPC 서버 (definitions 로드 에러)
docker compose logs --tail=50 dagster-rag-api

# 모든 컨테이너
docker compose logs --tail=50
```

### 3-2. Redis 큐 상태 확인

```bash
docker exec redis redis-cli -a <REDIS_PASSWORD>
LLEN rag:upload:queue    # 업로드 대기 수
LLEN rag:delete:queue    # 삭제 대기 수
ZCARD rag:upload:delay   # 재시도 대기 중인 업로드 수
ZCARD rag:delete:delay   # 재시도 대기 중인 삭제 수
```

### 3-3. 수동 재인덱스

**변경된 문서만 재처리** (ETag 비교, 정상 복구 시 우선 사용)

```bash
curl -X POST http://localhost:8000/api/kb/kb-01/reindex
```

**전체 강제 재인덱스** (인덱스 전체를 새로 쌓아야 할 때)

```bash
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex?force=true"
```

부하가 크므로 트래픽이 적은 시간대에 실행한다.

**단일 문서 재인덱스**

```bash
curl -X POST http://localhost:8000/api/kb/kb-01/docs/<doc_id>/reindex
```

### 3-4. Dagster 센서 관리

**센서 중지** (점검·배포 전, 진행 중 job이 끊기는 것을 방지)

```bash
docker exec dagster-daemon dagster sensor stop event_queue_sensor -w /opt/dagster/workspace.yaml
```

**센서 시작**

```bash
docker exec dagster-daemon dagster sensor start event_queue_sensor -w /opt/dagster/workspace.yaml
```

---

## 4. 배포 및 업데이트

### 4-1. 코드 업데이트 배포

인프라가 먼저 실행 중이어야 한다.

```bash
docker compose up -d postgresql redis qdrant minio
```

애플리케이션 이미지는 로컬 빌드이므로 `pull`이 아닌 `build`를 사용한다.

```bash
docker compose build rag-api dagster-rag-api
docker compose up -d rag-api dagster-rag-api
```

배포 후 확인:

```bash
curl -s http://localhost:8000/health
docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml
```

### 4-2. 롤백

이전 이미지 태그가 있는 경우:

```bash
# docker-compose.yml의 image 태그를 이전 버전으로 변경 후
docker compose up -d rag-api dagster-rag-api
```

이미지 태그가 없는 경우 git으로 소스를 되돌리고 재빌드한다.

```bash
git checkout <이전 커밋>
docker compose build rag-api dagster-rag-api
docker compose up -d rag-api dagster-rag-api
```

### 4-3. 커넥터 스케줄 변경 후 재시작

커넥터의 cron 표현식(`sync_schedule`)을 변경하면 Dagster가 반영하려면 재시작이 필요하다.

```bash
docker compose restart dagster-rag-api
```

재시작 후 Dagster UI > Schedules 에서 변경된 cron이 반영됐는지 확인한다.

> `schedule_enabled` 필드(API `PATCH /api/connectors/{id}`)는 재시작 없이 즉시 반영된다.

### 4-4. 인프라 이미지 업데이트

```bash
docker compose pull postgresql redis qdrant minio
docker compose up -d postgresql redis qdrant minio
```

### 4-5. 전체 재시작

```bash
docker compose down
docker compose up -d
```

전체 재시작 후 체크리스트:

1. `docker compose ps` — 모든 컨테이너 `healthy` 또는 `running`
2. `minio-init` — `Exited (0)` 확인
3. `curl -s http://localhost:8000/ready | jq` — 모든 체크 `true`
4. Dagster 센서 `RUNNING` 확인

---

## 5. 초기 설정 (일회성)

### 5-1. 자격증명 변경

`docker/.env`와 `docker/settings.yaml`의 초기값은 개발·테스트용이다. 프로덕션 배포 전에 반드시 변경한다.

**PostgreSQL**

`docker/init-db.sql`에서 유저·패스워드를 수정한다.
이 파일은 `pg_data` 볼륨이 없을 때 최초 기동 시에만 실행된다.

```sql
CREATE USER dagster WITH PASSWORD '새패스워드';
CREATE DATABASE dagster OWNER dagster;
CREATE USER "rag-api" WITH PASSWORD '새패스워드';
CREATE DATABASE "rag-api" OWNER "rag-api";
```

`docker/settings.yaml`과 `docker/docker-compose.yml`의 `DAGSTER_POSTGRES_URL`도 함께 수정한다.

```yaml
# docker/settings.yaml
postgres:
  password: "새패스워드"

# docker/docker-compose.yml (Dagster 컨테이너 3개 모두)
DAGSTER_POSTGRES_URL: postgresql://dagster:새패스워드@postgresql:5432/dagster
```

> 볼륨이 이미 생성된 상태에서 패스워드를 변경하려면 `docker compose down -v`로 볼륨을 삭제 후 재기동해야 한다. 저장된 데이터가 모두 삭제되므로 주의한다.

**Redis**

```bash
# docker/.env
REDIS_PASSWORD=새패스워드
```

```yaml
# docker/settings.yaml
redis:
  password: "새패스워드"
```

**MinIO**

```bash
# docker/.env
MINIO_ROOT_USER=새유저
MINIO_ROOT_PASSWORD=새패스워드
```

```yaml
# docker/settings.yaml
s3:
  access_key: "새유저"
  secret_key: "새패스워드"
```

MinIO 재기동 후 `minio-init`를 재실행해 버킷을 다시 초기화한다.

### 5-2. MinIO 초기화

`minio-init` 컨테이너가 최초 기동 시 버킷 생성(`rag-api`, `dagster-storage`)을 처리한다.

MinIO 재시작 후 버킷이 없어진 경우 재실행한다.

```bash
docker compose run --rm minio-init
```

이미 존재하는 버킷은 건너뛰므로 반복 실행해도 안전하다.

### 5-3. Redis AOF 영속성

기본 설정은 RDB 스냅샷 모드다. Redis 재시작 시 마지막 스냅샷 이후의 미처리 큐 이벤트가 유실될 수 있다.

AOF를 활성화하려면 `docker/docker-compose.yml`의 redis `command`를 수정한다.

```yaml
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD:-redis} --appendonly yes --appendfsync everysec
```

```bash
docker compose up -d --no-deps redis
```

큐가 유실된 경우 AOF 여부와 무관하게 reindex로 복구할 수 있다.

---

## 6. 컴포넌트 참조

### 컨테이너 구성

| 컨테이너 | 역할 | 포트 |
|---|---|---|
| `postgresql` | Postgres 15 — rag-api DB + Dagster 상태 저장소 | 5432 |
| `redis` | Redis 7 — 이벤트 큐 | 6379 |
| `qdrant` | Qdrant v1.18 — 벡터 DB | 6333 / 6334 |
| `minio` | MinIO — 오브젝트 스토리지 | 9000 / 9001(콘솔) |
| `minio-init` | 버킷 초기화 (일회성) | - |
| `rag-api` | RAG API 서버 | 8000 |
| `rag-admin` | 관리 UI (nginx) | 8080 |
| `dagster-rag-api` | gRPC 코드 서버 (definitions 로드) | 4000 |
| `dagster-webserver` | Dagster UI | 3000 |
| `dagster-daemon` | 센서·스케줄 실행 프로세스 | - |

### 이벤트 처리 흐름

`queue_worker.enabled: false` (기본값)일 때 Dagster가 이벤트를 처리한다.

```
API 호출 (파일 업로드 / 문서 삭제 / 커넥터 동기화)
  → rag-api: enqueue_upload_event / enqueue_delete_event
    → Redis 큐 (rag:upload:queue / rag:delete:queue)
      → event_queue_sensor (dagster-daemon, 30초 간격 tick)
        → ingest_job / delete_job
```

> `queue_worker.enabled: true`로 변경하면 Dagster 없이 rag-api 내장 워커가 큐를 직접 처리한다. 이 경우 Dagster 센서는 동작하지 않으며, 위 센서 관련 운영 절차는 해당 없다.

### 기동 의존 순서

```
postgresql  ─┐
redis ───────┼─(모두 healthy)→ rag-api ─→ rag-admin
qdrant ──────┤                        └─→ minio-init (minio healthy 추가)
minio ───────┘

postgresql ─(healthy)→ dagster-rag-api ─→ dagster-webserver
                                       └─→ dagster-daemon
```

### 오브젝트 스토리지 레이아웃

| source_type | storage_key 형식 | 예시 |
|---|---|---|
| `s3` (파일 업로드) | `{kb_id}/{filename}` | `kb-01/report.pdf` |
| `web` (크롤러) | `{kb_id}/web/{doc_id}.html` | `kb-01/web/a1b2c3-….html` |
| `confluence` | `{kb_id}/confluence/{doc_id}.md` | `kb-01/confluence/a1b2c3-….md` |
| `github` | `{kb_id}/github/{doc_id}.{ext}` | `kb-01/github/a1b2c3-….md` |

MinIO CLI로 오브젝트 확인:

```bash
docker exec minio mc alias set local http://localhost:9000 <user> <password>
docker exec minio mc ls local/rag-api/kb-01/
docker exec minio mc stat local/rag-api/kb-01/report.pdf
```
