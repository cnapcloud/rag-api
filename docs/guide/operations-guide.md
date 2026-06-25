# Operations Guide

운영자 및 배포 담당자를 위한 절차 가이드다.
내부 설계 및 데이터 구조는 [dev/design.md](../dev/design.md)를 참고한다.

---

## 이벤트 처리 흐름

`docker/settings.yaml`의 `queue_worker.enabled: false` (기본값)일 때 Dagster가 이벤트를 처리한다.

```
MinIO (PUT/DELETE)
  → POST http://rag-api:8000/internal/s3-event
    → Redis 큐 (rag:upload:queue / rag:delete:queue)
      → event_queue_sensor (dagster-daemon, 30초 간격 tick)
        → ingest_job / delete_job
```

이 흐름 중 어느 단계라도 끊기면 문서가 인제스트되지 않는다.
문제가 생겼을 때는 MinIO → rag-api → Redis 큐 → Dagster 센서 순서로 추적한다.

> `queue_worker.enabled: true`로 변경하면 Dagster 없이 rag-api 내장 워커가 큐를 직접 처리한다. 이 경우 Dagster 센서는 동작하지 않으며, 아래 센서 관련 운영 절차는 해당 없다.

---

## 1. 컨테이너 구성

| 컨테이너 | 역할 | 포트 |
|---|---|---|
| `postgresql` | Postgres 15 — rag-api DB + Dagster 상태 저장소 | 5432 |
| `redis` | Redis 7 — 이벤트 큐 | 6379 |
| `qdrant` | Qdrant v1.18 — 벡터 DB | 6333 / 6334 |
| `minio` | MinIO — 오브젝트 스토리지 | 9000 / 9001(콘솔) |
| `minio-init` | 버킷·webhook 구독 초기화 (일회성) | - |
| `rag-api` | RAG API 서버 | 8000 |
| `rag-admin` | 관리 UI (nginx) | 8080 |
| `dagster-rag-api` | gRPC 코드 서버 (definitions 로드) | 4000 |
| `dagster-webserver` | Dagster UI | 3000 |
| `dagster-daemon` | 센서·스케줄 실행 프로세스 | - |

**기동 의존 순서**

인프라 4개(`postgresql`, `redis`, `qdrant`, `minio`)는 서로 독립적으로 기동한다.

```
postgresql  ─┐
redis ───────┼─(모두 healthy)→ rag-api ─→ rag-admin
qdrant ──────┤                        └─→ minio-init (minio healthy 추가)
minio ───────┘

postgresql ─(healthy)→ dagster-rag-api ─→ dagster-webserver
                                       └─→ dagster-daemon
```

`rag-api` 스택과 `dagster` 스택은 서로 의존하지 않는다.
`dagster-rag-api`가 내려가면 daemon이 gRPC 연결 실패로 센서를 tick할 수 없다.
재시작 후 daemon 로그에 아래 메시지가 찍히면 정상 복구된 것이다.

```
Received LocationStateChangeEventType.LOCATION_UPDATED event for location grpc:dagster-rag-api:4000
```

### 전체 상태 확인

```bash
docker compose ps
docker compose logs --tail=50 dagster-daemon
```

---

## 2. 일상 운영

### Redis 큐 상태 확인

패스워드는 `docker/.env`의 `REDIS_PASSWORD` 값을 사용한다.

```bash
docker exec redis redis-cli -a <REDIS_PASSWORD>
LLEN rag:upload:queue    # 대기 중인 업로드 이벤트 수
LLEN rag:delete:queue    # 대기 중인 삭제 이벤트 수
ZCARD rag:upload:delay   # 재시도 대기 중인 업로드 수
ZCARD rag:delete:delay   # 재시도 대기 중인 삭제 수
```

큐가 계속 쌓이기만 하고 줄지 않으면 dagster-daemon 로그와 센서 상태를 점검한다.

### Dagster 센서 관리

**상태 확인**

```bash
docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml
```

`event_queue_sensor` 상태가 `RUNNING`이어야 한다.

**센서 시작**

방법 1 — Dagster UI (포트 3000)
```
Deployment > grpc:dagster-rag-api:4000 > Sensors > event_queue_sensor > Running 토글
```

방법 2 — CLI
```bash
docker exec dagster-daemon dagster sensor start event_queue_sensor -w /opt/dagster/workspace.yaml
```

**센서 중지**

```bash
docker exec dagster-daemon dagster sensor stop event_queue_sensor -w /opt/dagster/workspace.yaml
```

점검이나 배포 전에 센서를 먼저 중지하면 진행 중인 job이 중간에 끊기는 상황을 예방할 수 있다.






---

## 3. 인제스트 수동 트리거 (reindex)

### 변경된 파일만 재처리

MinIO의 현재 파일 목록과 DB 상태를 ETag로 비교해 차이가 있는 것만 큐에 넣는다.
큐 유실 직후 빠른 복구에 사용한다.

```bash
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex"
```

### 전체 강제 재인제스트

ETag 비교 없이 KB 내 모든 문서를 재처리한다.
인덱스 전체를 새로 쌓아야 할 때 사용한다.

```bash
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex?force=true"
```

> `kb-01` 자리에 실제 KB ID를 넣는다.
> 전체 강제 재인제스트는 처리 시간이 길고 부하가 크므로 트래픽이 적은 시간대에 실행한다.

---

## 4. 배포 및 재시작

### 코드 업데이트 배포

인프라(postgresql, redis, qdrant, minio)가 실행 중인지 먼저 확인한다.

```bash
docker compose up -d postgresql redis qdrant minio
```

인프라가 모두 healthy 상태가 된 후 애플리케이션을 빌드·배포한다.
애플리케이션 이미지는 로컬 빌드(`build:` 블록)이므로 `pull`이 아닌 `build`를 사용한다.

```bash
docker compose build rag-api dagster-rag-api
docker compose up -d rag-api dagster-rag-api
```

`dagster-rag-api`가 재시작되면 daemon이 자동으로 재연결을 시도한다.
daemon 로그에 `LOCATION_UPDATED` 메시지가 나오는지 확인한다.

### 인프라 이미지 업데이트

인프라 이미지 버전을 올릴 때만 실행한다.

```bash
docker compose pull postgresql redis qdrant minio
docker compose up -d postgresql redis qdrant minio
```

### 전체 재시작

```bash
docker compose down
docker compose up -d
```

전체 재시작 후 체크리스트:

1. `docker compose ps` — 모든 컨테이너 `healthy` 또는 `running`
2. `minio-init`가 정상 종료(`Exited (0)`)되었는지 확인
3. Redis 큐에 이벤트가 적체되어 있지 않은지 확인
4. 센서 상태 `RUNNING` 확인

---

## 5. MinIO Webhook

`minio-init` 컨테이너가 최초 기동 시 버킷 생성(`rag-api`, `dagster-storage`)과 webhook 이벤트 구독을 모두 처리한다.

MinIO가 재시작된 후 파일 업로드 이벤트가 rag-api에 오지 않으면 `minio-init`를 재실행한다.

```bash
docker compose run --rm minio-init
```

`--ignore-existing`이 적용되어 있으므로 이미 존재하는 버킷·구독은 건너뛴다. 반복 실행해도 안전하다.

| 항목 | 내용 |
|---|---|
| `--event` 형식 | `put,delete` — `s3:ObjectCreated:*` 형식이 아님 |
| 엔드포인트 경로 | `/internal/s3-event` (`/internal` prefix 포함) |
| MinIO 재시작 후 | 버킷 구독은 자동 복구되지 않으므로 `minio-init` 재실행 필요 |

---

## 6. 오브젝트 스토리지 레이아웃

MinIO에 저장되는 오브젝트의 경로(`storage_key`)와 첨부 메타데이터 구조를 설명한다.

### storage_key 형식

인제스트 경로에 따라 key 형식이 다르다.

| source_type | storage_key 형식 | 예시 |
|---|---|---|
| `s3` (파일 업로드) | `{kb_id}/{filename}` | `kb-01/report.pdf` |
| `web` (크롤러) | `{kb_id}/web/{doc_id}.html` | `kb-01/web/a1b2c3-….html` |
| `confluence` | `{kb_id}/confluence/{doc_id}.md` | `kb-01/confluence/a1b2c3-….md` |
| `github` | `{kb_id}/github/{doc_id}.{ext}` | `kb-01/github/a1b2c3-….md` |

파일 업로드는 원본 파일명을 그대로 사용한다.
커넥터 소스는 URL이나 페이지 ID를 파일 경로로 쓸 수 없으므로 `doc_id`(UUID)를 파일명으로 사용한다.

### 오브젝트 메타데이터

모든 오브젝트는 저장 시 아래 메타데이터(`x-amz-meta-*`)를 함께 기록한다.
파이프라인이 아닌 운영·복구 목적으로 오브젝트 자체를 self-describing하게 만들기 위함이다.

| 키 | 값 | 예시 |
|---|---|---|
| `doc-id` | doc_id UUID | `a1b2c3d4-…` |
| `kb-id` | KB ID | `kb-01` |
| `source-type` | 소스 유형 | `web` |
| `source` | 사용자 표시 이름 | `report.pdf` / `Getting Started` |
| `source-uri` | 정규화된 원본 URI | `https://example.com/docs/guide` |

MinIO 콘솔 또는 아래 CLI로 확인할 수 있다.

```bash
docker exec minio mc stat local/rag-api/kb-01/report.pdf
```

### source_uri 중복 방지 키

`source_uri`는 동일 문서 판별에 사용되는 dedup key다. 웹 소스는 아래 규칙으로 정규화된다.

| 규칙 | 변환 전 | 변환 후 |
|---|---|---|
| https 강제 | `http://example.com/page` | `https://example.com/page` |
| 호스트 소문자 | `https://Example.COM/page` | `https://example.com/page` |
| 끝 슬래시 제거 | `https://example.com/docs/` | `https://example.com/docs` |
| fragment 제거 | `https://example.com/page#section` | `https://example.com/page` |
| 트래킹 파라미터 제거 | `?utm_source=x` | 제거됨 |
| 쿼리 파라미터 정렬 | `?b=2&a=1` | `?a=1&b=2` |

---

## 7. Redis AOF 영속성

현재 `docker/docker-compose.yml`의 Redis는 기본 RDB 스냅샷 모드로 동작한다.
Redis 재시작 시 마지막 스냅샷 이후의 미처리 큐 이벤트가 유실될 수 있다.

AOF를 활성화하려면 `docker/docker-compose.yml`의 redis `command`를 수정한다.

```yaml
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD:-redis} --appendonly yes --appendfsync everysec
```

변경 적용:

```bash
docker compose up -d --no-deps redis
```

`appendfsync everysec`: 1초 단위 fsync — 성능과 내구성의 균형.
큐가 유실된 경우 AOF 여부와 무관하게 reindex로 복구한다.

---

## 8. 자격증명 변경

`docker/.env`와 `docker/settings.yaml`의 초기값은 개발·테스트용이다. 프로덕션 배포 전에 변경한다.

### PostgreSQL

`docker/init-db.sql`에서 유저·패스워드를 수정한다.
이 파일은 `pg_data` 볼륨이 없을 때 최초 기동 시에만 실행된다.

```sql
CREATE USER dagster WITH PASSWORD '새패스워드';
CREATE DATABASE dagster OWNER dagster;
CREATE USER "rag-api" WITH PASSWORD '새패스워드';
CREATE DATABASE "rag-api" OWNER "rag-api";
```

`docker/settings.yaml` postgres 섹션도 함께 수정한다.

```yaml
postgres:
  password: "새패스워드"
```

`docker/docker-compose.yml`에서 Dagster 컨테이너 3개의 `DAGSTER_POSTGRES_URL`도 수정한다.

```yaml
DAGSTER_POSTGRES_URL: postgresql://dagster:새패스워드@postgresql:5432/dagster
```

> 볼륨이 이미 생성된 상태에서 패스워드를 변경하려면 `docker compose down -v`로 볼륨을 삭제 후 재기동해야 한다. 저장된 데이터가 모두 삭제되므로 주의한다.

### Redis

`docker/.env`에서 패스워드를 수정한다.

```bash
REDIS_PASSWORD=새패스워드
```

`docker/settings.yaml` redis 섹션도 함께 수정한다.

```yaml
redis:
  password: "새패스워드"
```

### MinIO

`docker/.env`에서 루트 유저·패스워드를 수정한다.

```bash
MINIO_ROOT_USER=새유저
MINIO_ROOT_PASSWORD=새패스워드
```

`docker/settings.yaml` s3 섹션도 함께 수정한다.

```yaml
s3:
  access_key: "새유저"
  secret_key: "새패스워드"
```

MinIO 재기동 후 `minio-init`를 재실행해 구독을 다시 등록한다.

---

## 9. 트러블슈팅

| 증상 | 확인 포인트 |
|---|---|
| 파일 업로드 후 문서 상태가 변하지 않음 | MinIO webhook 구독 → Redis 큐 → Dagster 센서 순서로 추적 |
| rag-api가 기동하지 않음 | `postgresql`, `redis`, `qdrant`, `minio` 4개 모두 healthy인지 확인 |
| Redis 큐가 계속 쌓임 | dagster-daemon 로그에서 job 실행 에러 확인 |
| Dagster 센서가 계속 STOPPED로 돌아옴 | `dagster-rag-api` 컨테이너 상태 및 gRPC 포트(4000) 연결 확인 |
| Dagster UI에서 run 기록이 없음 | `postgresql` 컨테이너 상태 확인 |
| minio-init가 Exited (1)로 종료 | rag-api 기동 완료 전에 실행된 경우 — `docker compose run --rm minio-init`으로 재실행 |

추가 사례는 [troubleshooting/dagster-sensor-storage.md](../troubleshooting/dagster-sensor-storage.md)를 참고한다.
