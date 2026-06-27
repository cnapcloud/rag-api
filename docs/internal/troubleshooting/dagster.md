# Dagster 트러블슈팅

## 센서가 동작하지 않을 때

### 1. 컨테이너 상태 확인

```bash
docker ps | grep -E "dagster-rag-api|dagster-webserver|dagster-daemon|postgresql"
```

4개 컨테이너가 모두 `Up` 상태여야 한다.

### 2. 센서 상태 확인

```bash
docker exec dagster-daemon dagster sensor list -w /opt/dagster/workspace.yaml
```

`STOPPED`이면 수동으로 시작한다.

```bash
docker exec dagster-daemon dagster sensor start event_queue_sensor -w /opt/dagster/workspace.yaml
```

### 3. daemon 로그 확인

```bash
docker logs dagster-daemon --tail 50
```

gRPC 연결 오류(`grpc:dagster-rag-api:4000`)가 보이면 `dagster-rag-api` 컨테이너가 내려간 것이 원인이다.

```bash
docker restart dagster-rag-api
```

재시작 후 daemon 로그에 아래 메시지가 나오면 복구된 것이다.

```
Received LocationStateChangeEventType.LOCATION_UPDATED event for location grpc:dagster-rag-api:4000
```

---

## 코드 서버 재시작 시 run이 STARTED 상태로 멈추는 문제

**증상**

`dagster-rag-api` 컨테이너를 재시작(배포, 설정 변경 등)한 직후, 재시작 전에 실행 중이던 run들이 Dagster UI에서 영구적으로 "Starting" 상태로 남는다. daemon 로그에서 MonitoringDaemon이 같은 run ID를 2분 간격으로 계속 체크하는 것으로 확인할 수 있다.

```
dagster.daemon.MonitoringDaemon - INFO - Collected 2 runs for monitoring
dagster.daemon.MonitoringDaemon - INFO - Checking run e0f30fec-7242-4fc5-bdc7-162b6bb88f92
dagster.daemon.MonitoringDaemon - INFO - Checking run 1d54887f-df85-415d-abf5-d956dc4c8d28
```

**원인**

코드 서버가 중단될 때 실행 중이던 worker 프로세스가 같이 죽는다. DB에는 `STARTED` 상태로 남지만 실제 프로세스가 없는 zombie run이 된다. MonitoringDaemon이 주기적으로 감지하지만, worker heartbeat 만료 시간(기본 2시간)이 지나야 자동으로 FAILED 처리된다.

**주의: `max_resume_run_attempts > 0` 설정 불가**

`DefaultRunLauncher`는 run resume을 지원하지 않기 때문에 `max_resume_run_attempts`를 1 이상으로 설정하면 daemon이 기동 시 크래시된다.

```
CheckError: The configured run launcher does not support resuming runs.
Set max_resume_run_attempts to 0 to use run monitoring.
```

**즉시 조치 (zombie run 수동 취소)**

```bash
# 취소할 run ID 확인
docker exec postgresql env PGPASSWORD=dagster psql -U dagster -d dagster \
  -c "SELECT run_id, status, to_timestamp(start_time) FROM runs WHERE status NOT IN ('SUCCESS','FAILURE','CANCELED') ORDER BY start_time;"

# Dagster UI에서 취소: http://localhost:3000 → Runs → 해당 run → Cancel
# 또는 GraphQL API로 취소
curl -X POST http://localhost:3000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query":"mutation { terminateRun(runId: \"<run_id>\") { __typename } }"}'
```

**예방 (`docker-compose.yml`)**

코드 서버 재시작 전 컨테이너가 graceful shutdown을 기다리도록 `stop_grace_period`를 설정한다. 단, Dagster gRPC 서버가 SIGTERM을 받아도 실행 중인 op을 즉시 중단하므로 zombie 발생을 완전히 막지는 못한다.

```yaml
dagster-rag-api:
  stop_grace_period: 120s
```

---

## DagsterExecutionLoadInputError: No such file or directory (storage/)

> **현재 설정에서는 재현되지 않는 오류다.** `S3PickleIOManager`가 op 출력을 MinIO에 저장하므로 로컬 `storage/` 경로를 사용하지 않는다. 기본 `FilesystemIOManager`를 사용하던 시절의 기록으로 남긴다.

**증상**
```
FileNotFoundError: /opt/dagster/dagster_home/storage/<run_id>/validate_op/valid_config
```

**원인**

기본 `FilesystemIOManager`는 op 출력을 `storage/<run_id>/<op_name>/` 경로에 파일로 저장한다.
re-execution(특정 step부터 재실행) 시 이전 run의 파일을 읽는데, named volume 없이 컨테이너가 재시작되면 ephemeral 파일시스템이 초기화되어 해당 파일이 사라진다.

현재는 `S3PickleIOManager`(`src/defs/resources/resources.py`)가 op 출력을 MinIO(`dagster-storage` 버킷)에 저장하므로 이 문제가 발생하지 않는다. `FilesystemIOManager`로 롤백하는 경우 아래 조치가 필요하다.

**조치**

`docker-compose.yml`에 `dagster-storage` named volume을 마운트하고 컨테이너를 재생성한다.

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

> volume 없이 실행된 이전 run은 아티팩트가 소실되어 re-execution이 불가하다. Dagster UI에서 **Re-execute All**로 처음부터 재실행해야 한다.
