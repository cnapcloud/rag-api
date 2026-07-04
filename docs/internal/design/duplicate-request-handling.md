# 중복 처리 요청 핸들링 (큐 dedup / duplicate dispatch)

동일 문서(doc_id)에 대한 처리 요청이 짧은 시간 안에 여러 번 들어올 때(업로드 재시도, KB 전체
reindex 반복 호출, 커넥터 sync 등), 어느 레이어에서 무엇을 근거로 막는지 정리한다.
[doc-state-flow.md](doc-state-flow.md)가 상태 전이 전체를 다룬다면, 이 문서는 그중 "중복 요청"
경로만 큐 레벨까지 파고들어 정리한 것이다.

---

## 1. 큐 기본 동작 — dedup 유무

| 큐 | Redis 자료구조 | 명령 | dedup |
|----|---------------|------|-------|
| 메인 큐 (`rag:upload:queue`, `rag:delete:queue`) | List | `lpush` / `rpop` | **없음** — 동일 doc_id payload가 동시에 여러 개 존재 가능 |
| 딜레이 큐 (`rag:upload:delay`, `rag:delete:delay`) | Sorted Set | `zadd` (member=payload, score=재시도 시각) | **있음** — 동일 payload는 기존 항목의 score만 갱신, 중복 누적 안 됨 |

메인 큐 자체엔 "이미 같은 문서가 큐에 있는지" 확인하는 로직이 없다. 딜레이 큐가 이 구조를 갖게
된 건 재시도 누적을 막기 위한 설계이고(`queue_worker.py` 모듈 docstring 참고), 메인 큐는 애초에
이 문제를 API 레벨 차단으로 막는다는 전제로 설계된 것으로 보인다.

---

## 2. API 레벨 차단 — 요청이 큐에 들어가기 전

`upload_doc` / `upload_docs_batch` / `reindex_doc` / `reindex_kb`(`docs.py`)는 큐에 넣기 전에
기존 문서의 `is_active(status)`를 먼저 확인한다.

```python
if is_active(ex_status):
    raise ConflictError(f"Document is active, try again later: doc_id={...} status={ex_status}")
```

`is_active()`는 `_STABLE_STATUSES = {indexed, failed, deleted, outdated}`의 여집합이므로
`uploading` / `pending` / `running` / `deleting` 모두 여기 걸린다. 즉 **`deleting` 중인 문서에
대한 새 처리 요청은 큐에 들어가지도 않고 API 단계에서 즉시 거부(409, 단건) 또는 skip 처리(배치/
KB 전체 reindex)된다.**

이 체크를 정상적으로 거치는 한, 같은 문서가 메인 큐에 중복으로 쌓이는 일은 없다. 문제는 이 체크를
거치지 않는 경로(동시 요청 레이스, 커넥터 sync처럼 `enqueue_upload_event()`를 직접 호출하는
경로)로 큐에 이미 들어간 이후다 — 아래 3절.

---

## 3. 큐 소비 레벨 처리 — 이미 큐에 들어간 이후

큐에서 이벤트를 꺼낼 때, 두 실행 모드는 서로 다른 기준으로 "지금 처리해도 되는가"를 판단한다.

### 3.1 queue_worker 모드 (`queue_worker.py`)

```python
s = doc.get("status", "")
if s == "deleting":
    delay; continue
if s == "running":
    delay; continue
```

**status만 본다.** Dagster의 run_id 같은 개념이 없기 때문에(`run_id`는 항상 `"direct"` 상수) 이
판단 기준이 곧 최선이다. `running`/`deleting`이면 무조건 딜레이 큐로 보내고, 나중에 다시 상태를
재확인한다.

**한계**: 실제 백그라운드 스레드가 이미 죽어서 사라진 경우(서버 크래시 등)에도 이 로직은 구분하지
못하고 계속 딜레이 큐로만 돌린다. TTL/heartbeat 기반 자동 복구는 이 프로젝트에서 의도적으로
채택하지 않았고([US-05](../../../.claude/backlogs/US-05-stuck-running-recovery.md) Out of
Scope), `POST /docs/{id}/fail` 또는 `POST /docs/{id}/recover`로 수동 개입해야 풀린다.

### 3.2 Dagster 센서 모드 (`event_queue_sensor.py` `_is_blocked_by_active_run()`)

```python
s = doc.get("status", "")
if s != "running":
    return False                     # 안 막힘 -> dispatch

prev_run_id = doc.get("run_id", "")
if not prev_run_id:
    return True                      # run_id 아직 미기록 -> 막되 재적재 없이 드롭

run = context.instance.get_run_by_id(prev_run_id)
if run is not None and not run.is_finished:
    delay; return True               # 살아있음 -> 딜레이
set_failed(...)                      # 죽었음(좀비) -> 복구
return False                         # 복구 후 이번 요청으로 dispatch 진행
```

status만 보는 queue_worker와 달리, **status=="running"이면 일단 막고, `run_id`가 있을 때만
Dagster에 "진짜 살아있는지" 물어본다.** run_id로 좀비 자동 판별이 가능하므로 살아있으면 딜레이,
죽었으면(좀비) 복구 후 이번 요청으로 dispatch한다. 반면 `run_id`가 아직 채워지지 않은 구간
(RunRequest yield 직후 ~ `validate_op`가 `context.run_id`를 기록하기 전, 즉 Dagster
QUEUED/STARTING 구간)에 도착한 중복 요청은 **딜레이 큐 재적재 없이 그냥 드롭**한다 — 이렇게 해야
두 번째 Dagster run이 중복 dispatch되는 것을 막을 수 있다([US-34](../../../.claude/backlogs/todo/US-34-connector-abort-missed-queued-run.md)와
같은 `run_id=""` 구간의 또 다른 증상).

딜레이가 아니라 드롭인 이유: `run_id`가 채워지지 않는 상태가 Dagster 쪽 문제로 계속 유지되면(run이
QUEUED에서 못 벗어남) 딜레이 재적재는 무한 루프가 된다. 타임아웃 기반 좀비 판정은 추가하지 않는다 —
queue_worker와 마찬가지로 이 프로젝트는 TTL 기반 자동 복구를 채택하지 않기로 했고, 이미 존재하는
`POST /docs/{id}/recover`가 수동 안전판 역할을 한다.

| 분기 | 결과 |
|------|------|
| `run_id` 있음 + 활성(살아있음) | 딜레이 큐로 이동 (정상) |
| `run_id` 있음 + 비활성(좀비) | 복구(`set_failed`) 후 이번 요청으로 dispatch 진행 (정상) |
| `run_id` 없음(`""`) | 막되 딜레이 재적재 없이 드롭 (중복 dispatch 방지) |

이 설계의 알려진 부작용:
- 드롭된 요청이 사실 "콘텐츠가 바뀌어서 재인덱싱이 필요하다"는 의미였다면, `content_version`
  (ETag)이 이전 버전 기준으로 남을 수 있다 — 이는 콘텐츠가 처리 도중 바뀌는 경우의 레이스이며,
  [known-issues.md 8절](../known-issues.md)에서 별도로 관리한다.
- `run_id`가 비어있는 상태가 Dagster 쪽 문제로 계속 유지되면(예: run이 QUEUED에서 계속 못
  벗어남), 그 문서에 대한 **모든 후속 요청이 계속 드롭**된다 — queue_worker의 "영원히 딜레이"와
  증상은 다르지만 본질(자동 복구 없음, 수동 개입 필요)은 같다.

---

## 4. 요약

| 레이어 | 판단 기준 | 결과 |
|--------|-----------|------|
| API 진입 (`docs.py`) | `is_active(status)` | 409 거부 / skip — 큐에 안 들어감 |
| queue_worker 소비 | `status` | `running`/`deleting` -> 무조건 딜레이 (좀비 자동 복구 없음) |
| Dagster 센서 소비 | `status` + `run_id` | `run_id` 있으면 좀비 판별(활성=딜레이/좀비=복구 후 dispatch), 없으면 막되 딜레이 대신 드롭 |

메인 큐(List) 자체의 중복 적재 가능성(1절)은 이 판별 로직으로 사라지지 않는다 — 다만 위 레이어들이
실질적 피해(이중 실행)를 억제하기 때문에 구조적 갭으로만 남는다.

---

## 5. 구현 위치

| 구성 요소 | 위치 |
|-----------|------|
| 메인/딜레이 큐 push | `src/rag_api/pipeline/queue/enqueue.py` |
| API 레벨 active 체크 | `src/rag_api/api/routers/docs.py` |
| queue_worker 소비/딜레이 | `src/rag_api/pipeline/queue/queue_worker.py` |
| Dagster 센서 소비/딜레이/좀비 복구 | `src/rag_api/defs/sensors/event_queue_sensor.py` (`_is_blocked_by_active_run`) |
| run_id 실제 기록 시점 | `src/rag_api/defs/ops/ingest_ops.py` (`validate_op`) |
