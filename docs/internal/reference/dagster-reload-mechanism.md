# Dagster Code Location Reload Mechanism

`reloadRepositoryLocation` GraphQL mutation이 어떻게 처리되는지,
진행 중인 sensor 프로세스에 어떤 영향을 주는지 기술한다.

---

## 컨테이너 구조

```
dagster-webserver  (:3000)   UI + GraphQL API
dagster-daemon               sensor/schedule 평가 루프
dagster-rag-api    (:4000)   dagster api grpc -f src/defs/definitions.py
rag-api            (:8000)   FastAPI (user-api)
postgresql                   run / event / schedule 상태 저장
```

webserver와 daemon은 모두 `workspace.yaml`이 지정한 gRPC 서버(`dagster-rag-api:4000`)로
연결하여 definitions(jobs, sensors, schedules, resources)를 수신한다.
상태(run 결과, sensor cursor, tick 기록)는 모두 Postgres에 저장된다.

---

## Reload 요청 처리 흐름

```
[1] rag-api / curl
      POST localhost:3000/graphql
      mutation reloadRepositoryLocation(repositoryLocationName: "grpc:dagster-rag-api:4000")

[2] dagster-webserver
      workspace의 location 상태를 "loading"으로 표시
      dagster-rag-api:4000 으로 gRPC Reload 호출

[3] dagster-rag-api 컨테이너 내부
      gRPC host process   ← 프로세스 유지, 포트 유지
        user code subprocess  ← 종료 후 재시작 (~2-5초)
          definitions.py 재임포트
          load_connector_schedules()  →  Postgres 재조회
          새 definitions 준비 완료

[4] dagster-webserver
      gRPC 재연결 → 새 definitions 수신
      location 상태 "loaded" 복귀
      GraphQL 응답: { __typename: "WorkspaceLocationEntry" }
```

gRPC **host process는 재시작되지 않는다.** user code subprocess만 교체된다.
따라서 포트 바인딩 단절은 없으며 reload 중에도 gRPC 엔드포인트는 살아있다.

---

## daemon의 sensor 평가 흐름

daemon은 sensor를 4단계로 처리한다.

```
[A] gRPC 호출
      dagster-rag-api:4000 에서 sensor 함수 직렬화 수신

[B] subprocess 실행
      daemon 자체 subprocess 에서 execution_fn 실행
      (이 subprocess는 gRPC 서버와 별개)

[C] RunRequest 제출
      Postgres run_queue 에 삽입 (QueuedRunCoordinator)

[D] cursor / tick 커밋
      Postgres schedule_storage 에 저장
```

---

## reload 타이밍별 영향

| daemon 단계 | reload 중 user code subprocess 재시작이 겹치면 |
|-------------|------------------------------------------------|
| [A] gRPC 호출 중 | gRPC 에러 → 이 tick만 FAILURE, daemon은 계속 실행 |
| [B] subprocess 실행 중 | **영향 없음** — daemon 독립 subprocess, gRPC 서버 무관 |
| [C] RunRequest 제출 | **영향 없음** — Postgres 직접 삽입 |
| [D] cursor 커밋 | **영향 없음** — Postgres 직접 저장 |

[A] 단계에서 실패하면 해당 tick 하나가 FAILURE로 기록되고
다음 `minimum_interval_seconds` 후 재시도된다.

---

## event_queue_sensor 관련 주의사항

`event_queue_sensor`는 Dagster cursor(`context.update_cursor()`)를 사용하지 않는다.
이벤트를 Redis `rpop`으로 **파괴적으로 소비**한다.

```
[A] 단계 실패 → tick 시작 안 됨 → rpop 없음 → 이벤트 보존 (안전)

[B] 단계 이미 실행 중:
    r.rpop(UPLOAD_QUEUE_KEY)   ← Redis에서 제거됨
              |
    [subprocess OOM / 컨테이너 강제 종료]   ← reload 무관한 기존 리스크
              |
    RunRequest yield 안 됨 → 이벤트 유실
```

reload 자체는 daemon subprocess에 영향을 주지 않으므로
**reload로 인한 이벤트 유실은 발생하지 않는다.**

---

## Reload 호출 방법

`reloadWorkspace`를 사용한다. `workspace.yaml`에 등록된 **모든 code location을 한 번에 재로드**하므로
location name을 설정에서 관리할 필요가 없다.

```bash
curl -X POST http://localhost:3000/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { reloadWorkspace { __typename ... on Workspace { locationEntries { name loadStatus } } ... on PythonError { message } } }"}'
```

성공 응답:
```json
{
  "data": {
    "reloadWorkspace": {
      "__typename": "Workspace",
      "locationEntries": [{ "name": "grpc:dagster-rag-api:4000", "loadStatus": "LOADED" }]
    }
  }
}
```

`rag-api`에서 호출할 때는 `infra/dagster_utils.py`의 `reload_code_location()`을 사용한다.
내부적으로 `cfg.dagster.endpoint`(`http://dagster-webserver:3000`)로 요청한다.

### reloadWorkspace vs reloadRepositoryLocation

| | `reloadWorkspace` | `reloadRepositoryLocation` |
|---|---|---|
| 대상 | workspace.yaml의 전체 location | 지정한 location 하나 |
| location name 관리 | 불필요 | 설정에서 관리 필요 |
| location 추가 시 | 자동 대응 | 설정 업데이트 필요 |
| 현재 채택 | Yes | No |

---

## 재로드되는 항목

`definitions.py`가 통째로 재실행되므로 한 파일에 등록된 모든 항목이 함께 교체된다.

| 항목 | 재로드됨 | 비고 |
|------|----------|------|
| schedules | Yes | 새 cron 식, 추가/삭제된 커넥터 반영 |
| sensors | Yes | |
| jobs | Yes | |
| resources | Yes | |
| 진행 중인 run | No | daemon이 별도 추적, 중단되지 않음 |
| sensor cursor | No | Postgres에 저장, reload 후에도 유지 |

---

## 주요 사용 시나리오

커넥터의 `sync_schedule`(cron 식) 변경, 커넥터 추가/삭제 후
새 `ScheduleDefinition`을 Dagster에 반영할 때 이 API를 호출한다.

`schedule_enabled` ON/OFF 및 `status` 변경은 `execution_fn` 내에서
실행 시점에 Postgres를 읽으므로 reload 없이 즉시 반영된다.
