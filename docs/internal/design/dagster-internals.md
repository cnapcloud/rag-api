# Dagster 내부 동작 원리

Dagster job/sensor/op 구조와 그 동작 방식. 큐 소비 시점의 중복/충돌 처리는
[duplicate-request-handling.md](duplicate-request-handling.md), 전체 런타임 흐름은
[architecture/runtime.md](../architecture/runtime.md) 참조.

---

## 1. Definitions 구조

```python
# src/defs/definitions.py
from dagster import Definitions
from rag_api.defs.jobs.ingest_job import ingest_job
from rag_api.defs.jobs import delete_job
from rag_api.defs.sensors.event_queue_sensor import event_queue_sensor
from rag_api.defs.resources.resources import build_resources_from_settings

defs = Definitions(
    jobs=[ingest_job, delete_job],
    sensors=[event_queue_sensor],
    resources=build_resources_from_settings(),  # S3PickleIOManager
)
```

`docker/dagster.yaml`의 `run_coordinator`(`QueuedRunCoordinator`)가 `max_concurrent_runs`로
동시 처리 문서 수를 제한한다.

---

## 2. ingest_job Op 구조 (`ingest_ops.py`)

```python
class IngestConfig(Config):
    kb_id: str
    doc_source: str
    etag: str
    file_size: int = 0
    force: bool = False

@op(out={"valid_config": Out(dagster_type=dict, is_required=False)})
def validate_op(context: OpExecutionContext, config: IngestConfig):
    set_processing(config.kb_id, config.doc_source, etag=config.etag, run_id=context.run_id)
    should_process = validate(kb_id, doc_source, etag, file_size, force)
    if should_process:
        yield Output({"kb_id": ..., "doc_source": ..., "run_id": context.run_id}, "valid_config")
    else:
        restore_indexed(config.kb_id, config.doc_source, etag=config.etag)

# parse_op -> chunk_op -> embed_op -> upsert_op -> meta_op 순서로 이어짐
```

### validate_op 역할 — run_id 등록 + ETag/버전 검증

```
validate_op
    │
    ├─ Postgres에서 기존 ETag 조회 (get_doc_etag)
    │       ├─ ETag 동일 → Output 미발행 → restore_indexed() → 파이프라인 종료
    │       └─ ETag 다름 또는 신규 → Output 발행 → 다음 Op 진행
    │
upsert_op
    ├─ Qdrant: 기존 청크 전체 삭제 (doc_key 필터)
    └─ Qdrant: 신규 청크 배치 삽입
```

`set_processing(..., run_id="")`으로 sensor가 남긴 dispatch lock을, `validate_op`가 실제
`context.run_id`로 갱신한다.

---

## 3. event_queue_sensor 구조 (`event_queue_sensor.py`)

```python
@sensor(jobs=[ingest_job, delete_job], minimum_interval_seconds=poll_interval_sec)
def event_queue_sensor(context: SensorEvaluationContext):
    # 1. delay 큐에서 준비된 항목을 main 큐로 복원
    _drain_delay_queue(r, UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY)
    _drain_delay_queue(r, DELETE_DELAY_KEY, DELETE_QUEUE_KEY)

    # 2. PUT 큐 처리 -> ingest_job (활성 run 있으면 delay, zombie면 recover 후 dispatch)
    # 3. DELETE 큐 처리 -> delete_job
    ...
```

### sensor vs validate_op 역할 경계

sensor는 큐 레벨에서 "언제 실행할지"를 결정(dispatch 가부)하고, validate_op는 job 레벨에서
"파일 자체가 유효한지"를 검증(인제스트 가부)한다.

| | sensor | validate_op |
|---|---|---|
| 책임 | dispatch 가부 결정 | 인제스트 가부 결정 |
| zombie 복구 | O (run_id 있는 경우만) | X |
| dispatch lock | `set_processing(run_id="")` | `set_processing(run_id=<실제값>)`으로 갱신 |
| ETag 중복 체크 | X | O |
| 파일 크기 체크 | X | O |

큐 소비 시점의 dedup/충돌 판단 로직 상세는 [duplicate-request-handling.md](duplicate-request-handling.md) 참조.

---

## 4. sensor `default_status` 동작 원리

`event_queue_sensor`는 `default_status=DefaultSensorStatus.RUNNING`으로 선언되어 있다.

- 이 값은 센서가 Dagster DB에 **처음 등록될 때만** 적용된다.
- 한 번 저장된 상태는 재배포나 재시작으로 바뀌지 않는다.
- STOPPED로 바뀌는 경우는 수동 stop 또는 DB 초기화뿐이다.

DB 초기화 후 재배포하면 신규 등록으로 처리되어 자동으로 RUNNING 상태가 된다.

---

## 5. 로깅 동작 원리

`pipeline/steps/` 순수 함수들은 `logging.getLogger(__name__)`을 사용한다.
Dagster는 기본적으로 이 로거를 감시하지 않으므로 Dagster UI에 로그가 나타나지 않는다.

`dagster.yaml`의 `managed_python_loggers`에 등록하면 Dagster UI에서도 볼 수 있다.

| 방식 | Dagster UI 노출 | 사용 위치 |
|------|----------------|-----------|
| `context.log.info()` | 항상 | Dagster op 래퍼 (`defs/ops/`) |
| `logging.getLogger(__name__)` 기본 | X | 순수 함수 (`pipeline/steps/`) |
| `logging.getLogger(__name__)` + `managed_python_loggers` | O | 순수 함수, 설정 후 |

---

## 6. 구현 위치

| 구성 요소 | 위치 |
|-----------|------|
| Definitions | `src/defs/definitions.py` |
| ingest_job Op | `src/defs/ops/ingest_ops.py` |
| event_queue_sensor | `src/defs/sensors/event_queue_sensor.py` |
| Dagster 설정 (run_coordinator, managed_python_loggers) | `docker/dagster.yaml` |
