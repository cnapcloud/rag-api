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
