# Known Issues

발견된 이슈를 기록하는 문서. 해결 시 상태를 `open` -> `resolved`로 변경하고 해결 방법을 기록한다.

---

## 목차

- [Known Issues](#known-issues)
  - [목차](#목차)
  - [1. DELETE /docs/{doc\_id} returns 200 for non-existent document](#1-delete-docsdoc_id-returns-200-for-non-existent-document)
  - [2. Dagster SensorDefinition owners parameter BetaWarning](#2-dagster-sensordefinition-owners-parameter-betawarning)
  - [3. 커넥터 동기화 중단 불가](#3-커넥터-동기화-중단-불가)
  - [4. Delete + Reindex race condition](#4-delete--reindex-race-condition)
  - [5. SimHash/MinHash 동시 유사 문서 누락](#5-simhashminhash-동시-유사-문서-누락)
  - [6. Connector abort 시 DagsterExecutionInterruptedError STEP\_FAILURE 로그](#6-connector-abort-시-dagsterexecutioninterruptederror-step_failure-로그)
  - [7. rag-ent-api make install 실패 — Python 3.14와 tree-sitter-languages 비호환](#7-rag-ent-api-make-install-실패--python-314와-tree-sitter-languages-비호환)
  - [8. 동일 문서 중복 처리 요청 시 모드별 회복 불가 케이스](#8-동일-문서-중복-처리-요청-시-모드별-회복-불가-케이스)
  - [9. 커넥터 abort 시 센서 pop~RunRequest 구간의 서브초 레이스로 취소 대상 누락](#9-커넥터-abort-시-센서-poprunrequest-구간의-서브초-레이스로-취소-대상-누락)

---

## 1. DELETE /docs/{doc_id} returns 200 for non-existent document

| 항목 | 내용 |
|------|------|
| 상태 | resolved |
| 발견일 | 2026-06-19 |
| 해결일 | 2026-06-26 |
| 심각도 | LOW |

**증상**

존재하지 않는 문서를 삭제 요청해도 `200`이 반환됐다.

**원인**

`DELETE /api/kb/{kb_id}/docs/{doc_id}` 라우터가 삭제 전 문서 존재 여부를 확인하지 않았다.

**해결**

`get_doc_by_id`로 Postgres에서 문서를 조회하고, 없거나 `kb_id`가 불일치하면 `NotFoundError`(404)를 반환한다.

```python
doc = get_doc_by_id(doc_id)
if doc is None or doc.get("kb_id") != kb_id:
    raise NotFoundError(f"Document not found: kb={kb_id} doc_id={doc_id}")
```

---

## 2. Dagster SensorDefinition owners parameter BetaWarning

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-06-19 |
| 심각도 | LOW |

**증상**

Dagster daemon 시작 시 아래 경고가 출력된다.

```
/usr/local/lib/python3.12/site-packages/dagster/_core/definitions/sensor_definition.py:809:
BetaWarning: Parameter `owners` of initializer `SensorDefinition.__init__` is currently
in beta, and may have breaking changes in minor version releases, with behavior changes
in patch releases.
```

**원인**

`SensorDefinition` (또는 `@sensor` 데코레이터) 초기화 시 `owners` 파라미터를 전달하고 있으나,
해당 파라미터가 Dagster 1.7에서 아직 베타 상태다.

**해결 방안**

Option A — `owners` 파라미터 제거:

센서 정의에서 `owners=[...]` 인자를 삭제한다. 소유자 정보가 필요하지 않다면 가장 간단한 해결책.

Option B — 경고 억제 (임시방편):

```python
import warnings
from dagster import BetaWarning
warnings.filterwarnings("ignore", category=BetaWarning)
```

**비고**

Dagster가 `owners` 파라미터를 정식 릴리스하면 경고는 자동으로 사라진다.
현재 기능 동작에는 영향 없음.

---

## 3. 커넥터 동기화 중단 불가

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-06-26 |
| 심각도 | MED |

**증상**

`POST /sync`로 시작된 동기화를 중간에 중단할 방법이 없다. `POST /sync/reset`은 DB의 `sync_status`를 `idle`로 초기화할 뿐, 실행 중인 작업을 멈추지 않는다.

**원인**

동기화는 FastAPI `BackgroundTask`(일반 Python 스레드)로 실행된다. 완전한 중단을 위해서는 네 가지를 동시에 처리해야 한다:

1. **커넥터 수집 루프 중단** — 파일 fetch 루프에 abort 플래그 체크 추가
2. **Redis 인제스트 큐에서 해당 커넥터 항목 제거** — Redis list는 특정 항목만 골라내는 atomic 연산이 없어 drain 후 재투입 방식만 가능
3. **Dagster 실행 대기(QUEUED/STARTING) run 제거** — Dagster run queue에 쌓인 미시작 run을 GraphQL `terminateRun()`으로 제거 필요
4. **실행 중인 Dagster job 취소** — GraphQL `terminateRun()` 호출 필요

**현재 대안**

`POST /api/connectors/{id}/sync/abort`로 수집 루프를 중단할 수 있다. 커넥터가 파일/URL을 처리할 때마다 abort 플래그를 확인하고 감지 시 즉시 루프를 종료한다. `abort_sync()`는 Redis 큐/딜레이 큐에 남아있는 문서(`status=pending`)는 `dequeue_upload_events()`로 제거하고, 실행 중(`status=running`) 문서는 `run_id`가 기록되어 있으면 `terminate_dagster_run(run_id)`로 바로 종료하며, `run_id`가 아직 기록되지 않은(QUEUED/STARTING 구간) 문서는 `find_active_run_ids_by_doc_ids(doc_id)`로 Dagster GraphQL에서 `doc_id` 태그로 활성 run을 조회해 종료 대상에 포함한다(2026-06-28 `c770ddb` 최초 추가, 2026-07-04 US-34로 QUEUED/STARTING 구간 gap 해소 — 관련 부작용은 [이슈 6](#6-connector-abort-시-dagsterexecutioninterruptederror-step_failure-로그) 참조).

**진행 상황 (2026-07-04 업데이트 — US-34 구현 완료)**

- 항목 1, 2, 4는 기존 방식으로 구현되어 있음을 코드로 확인.
- 항목 3(QUEUED/STARTING run 제거)은 `infra/dagster_utils.py`의 `find_active_run_ids_by_doc_ids()`(GraphQL `runsOrError(filter: {statuses: [QUEUED, STARTING, STARTED, CANCELING]})` 조회 후 `doc_id` 태그로 client-side 필터링)와 `abort_sync()`의 호출로 해결됨. `run_id`가 없는 `status=running` 문서의 `doc_id`를 모아 조회하고, 반환된 run_id를 기존 종료 대상 집합에 합쳐 `terminate_dagster_run()`으로 종료한다.
  - 이와 별개로 센서 한 틱 안에서 "Redis 이벤트 pop"과 "RunRequest yield" 사이의 아주 짧은 순간에 abort가 끼어드는 서브초 단위 레이스가 있다. 상세 내용은 [이슈 9](#9-커넥터-abort-시-센서-poprunrequest-구간의-서브초-레이스로-취소-대상-누락) 참조.
  - 근본 원인과 관련 메커니즘(메인 큐 dedup 부재, `_is_blocked_by_active_run()`의 `run_id` 의존성)은 [duplicate-request-handling.md](design/duplicate-request-handling.md) 참조.
- **queue_worker 모드(`queue_worker.enabled=true`, Dagster 미사용)에서는 abort/force-fail로 실행 중인 백그라운드 작업을 아예 종료할 수 없는 별도 gap이 남아있다.** 이 모드에서는 `QueueWorker`(`pipeline/queue/queue_worker.py`)가 Redis 큐를 직접 `r.rpop()`으로 꺼내 `asyncio.create_task()` -> `ThreadPoolExecutor`로 ingest/delete를 실행하는데, 이 태스크가 어디에도 등록되지 않아 취소할 방법이 없다. `dagster_utils.terminate_dagster_run()`은 `queue_worker.enabled=true`일 때 무조건 no-op(`infra/dagster_utils.py:75-77`)이라 애초에 대상이 되지 않는다.
  - `POST /{connector_id}/sync/abort`(`connectors.py` `abort_sync()`)는 `dequeue_upload_events()`로 아직 Redis에 남은 항목만 제거하고, 이미 `r.rpop()`으로 꺼내져 실행 중인 문서는 `set_failed(doc_id, "Aborted")`로 상태만 바뀔 뿐 실제 스레드는 계속 실행되어 완료 시 상태를 덮어쓸 수 있다. **경고 없이 202로 성공 응답한다.**
  - `POST /kb/{kb_id}/docs/{doc_id}/fail`(`docs.py` `force_fail_doc()`)은 동일한 한계를 이미 코드에서 인지하고 있으며(`worker_mode_active` 체크, L385-404), 응답에 `"queue_worker mode has no terminate support"` 경고 필드를 포함한다. `abort_sync()`에는 이 경고가 없다.
  - **정정 (2026-07-03)**: 처음엔 "doc_id -> Task 레지스트리 + `task.cancel()`"을 근본 해결책으로 적었으나 부정확함. `run_in_executor(executor, func)`는 `concurrent.futures.Future`를 asyncio Future로 래핑하는데, 워커 스레드가 이미 `func`(=`run_ingest_pipeline`) 실행을 시작한 뒤에는 `concurrent.futures.Future.cancel()`이 무조건 `False`를 반환한다 — Python 스레드는 외부에서 안전하게 강제 종료할 수 없기 때문이다. 이 상태에서 바깥 asyncio Task에 `.cancel()`을 호출하면 asyncio 쪽 장부만 CANCELLED로 마킹되고 `await` 지점에서 `CancelledError`가 올라올 뿐, 실제 워커 스레드는 아무도 기다리지 않는 채로 끝까지 실행되어 여전히 자기 결과로 상태를 덮어쓴다. `task.cancel()`이 실제로 막을 수 있는 건 아직 세마포어(`self._semaphore`)를 획득하지 못해 실행이 시작조차 안 된 대기 중인 태스크뿐이다.
    진짜 해결하려면 둘 중 하나가 필요하다: (a) `run_ingest_pipeline`/각 op(parse/chunk/embed/upsert) 내부에 협조적 취소 체크포인트를 op 경계마다 심기(파이프라인 전체를 건드려야 함), 또는 (b) 스레드 대신 별도 OS 프로세스(`ProcessPoolExecutor`/subprocess)로 실행해 SIGTERM으로 강제 종료 — Dagster 모드의 `terminateRun()`이 실제로 작동하는 이유가 바로 이것(job이 별도 프로세스로 실행됨)이다. 아직 백로그 미등록.

**미해결**

서브초 단위 레이스(known limitation), queue_worker 모드 태스크 취소(백로그 미등록)는 미구현 상태. Dagster 모드의 QUEUED/STARTING run 제거(US-34)는 해결됨.

---

## 4. Delete + Reindex race condition

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-06-26 |
| 심각도 | LOW |

**증상**

문서 삭제 요청 직후 reindex를 요청하면, 삭제 job이 완료되기 전에 ingest job이 큐에 추가된다. 이후 삭제 job이 S3 파일을 지우고 나서 ingest job이 실행되면 파일을 찾지 못해 실패한다.

**원인**

`enqueue_delete_event`와 `enqueue_upload_event` 모두 doc status를 `pending`으로 설정한다. reindex 로직이 `include_deleted=False`(즉 `deleted_at IS NULL`) 기준으로 대상 문서를 조회하기 때문에, 삭제 큐에 들어간 문서(`pending` 상태)도 reindex 대상에 포함된다.

**발생 조건**

삭제 요청과 reindex 요청이 delete job 실행 전에 연속으로 발생해야 하므로 실제 발생 빈도는 낮다.

**현재 동작**

ingest job이 S3 파일을 찾지 못해 실패하고 doc status가 `failed`로 남는다. 이미 soft-delete된 상태이므로 사용자에게 노출되지 않으며, 데이터 정합성은 유지된다.

**해결 방안 (미적용)**

"in-flight 문서에 대한 새 작업 차단" 방식으로 해결할 수 있으나, 비정상 종료 시 `pending`/`running` 상태에 stuck되는 문서 복구 문제(startup reset, timeout 기반 복구 등)를 함께 구현해야 한다. 현재 피해가 graceful한 수준이므로 복잡도 대비 이득이 낮아 보류.

---

## 5. SimHash/MinHash 동시 유사 문서 누락

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-06-27 |
| 심각도 | MED |

**증상**

내용이 동일하거나 유사한 문서가 거의 동시에 인제스트되면, SimHash/MinHash 중복 감지가 두 문서 모두를 통과시켜 Qdrant에 중복 청크가 삽입될 수 있다.

**원인**

SimHash/MinHash 탐지는 Postgres에 이미 저장된 simhash/minhash band 값을 기준으로 비교한다. 두 인제스트 job이 동시에 실행되면 각각 "현재 DB에 일치하는 문서 없음"으로 판정한 뒤 서로의 band 값을 모른 채로 upsert를 진행한다. 즉, 탐지 조회(read)와 band 저장(write) 사이에 원자성이 없다.

**발생 조건**

동일 또는 유사 문서가 짧은 시간 간격으로 복수의 인제스트 job으로 처리될 때 발생한다. 단일 job이 순차 처리되는 경우에는 재현되지 않는다.

**현재 동작**

중복 청크가 Qdrant에 삽입되고, 검색 결과에 동일 내용이 중복으로 노출될 수 있다. 데이터 정합성 오류이지만 서비스 중단은 발생하지 않는다.

**향후 해결 방안**

SimHash/MinHash 탐지-저장 구간을 Redis 분산 락(예: `SET NX PX` 또는 Redlock)으로 보호하여, 동일 KB 내에서 한 번에 하나의 인제스트만 dedup 단계를 원자적으로 수행하도록 직렬화한다. 락 범위는 KB 단위로 하되, 락 TTL은 단일 dedup 처리 예상 시간보다 충분히 크게 설정해야 한다.

---

## 6. Connector abort 시 DagsterExecutionInterruptedError STEP_FAILURE 로그

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-06-28 |
| 심각도 | LOW |

**증상**

`POST /api/connectors/{id}/sync/abort` 호출 시, 실행 중이던 Dagster step이 `DagsterExecutionInterruptedError`로 STEP_FAILURE를 남긴다.

```
dagster._core.errors.DagsterExecutionInterruptedError
  File "pipeline/ops/dedup/minhash.py", line 161, in run_minhash_detection
      logger.info("no candidates doc_id=%s", doc_id)
  ...
  File "dagster/_utils/interrupts.py", line 81, in _new_signal_handler
      raise error_cls()
```

**원인**

`abort_sync`가 `terminate_dagster_run(run_id)`을 호출하면 Dagster가 워커 프로세스에 SIGTERM을 보내고 signal handler를 등록한다. 이 handler는 다음 Python bytecode 실행 시 `DagsterExecutionInterruptedError`를 발생시킨다. 타이밍에 따라 Dagster 내부 로깅 코드(`psycopg2.connect`)에서 인터럽트가 발생해 스택 트레이스가 길게 찍힌다.

**상태 일관성**

버그가 아니며 데이터 정합성 문제 없음:

- `abort_sync`는 `terminate_dagster_run` 호출 **전에** `set_failed(doc_id, "Aborted")`를 호출하므로 doc status는 항상 올바르게 세팅됨
- `minhash_bands`는 `ON CONFLICT DO UPDATE` upsert이므로 재인제스트 시 덮어씌워짐
- `body_candidates.discard(doc_id)`로 자기 자신과의 중복 매칭 방지됨

**현재 동작**

로그 노이즈. 이후 동일 doc에 대한 새 run이 `validate_op`에서 `status == "failed"` 감지 후 조기 종료됨.

**해결 방안**

수정 불필요. 알람/모니터링에서 `DagsterExecutionInterruptedError`를 abort로 구분하고 싶다면 run tag나 Dagster run status(`CANCELED` vs `FAILURE`)로 필터링한다.

---

## 7. rag-ent-api make install 실패 — Python 3.14와 tree-sitter-languages 비호환

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-07-03 |
| 심각도 | LOW |

**증상**

`rag-ent-api`에서 `make install`(`uv sync`) 실행 시 실패한다.

**원인**

1. `uv`가 `rag-ent-api`의 가상환경으로 Python 3.14를 선택한다.
2. `rag-ent-api`는 `../rag-api`를 editable 의존성으로 물고 있다.
3. `rag-api`는 코드 청킹에 `llama_index.core.node_parser.CodeSplitter`를 사용한다.
4. `CodeSplitter`는 내부적으로 `tree-sitter-languages` 패키지에 의존한다.
5. `tree-sitter-languages==1.10.2`(최신 버전)는 `cp311`/`cp312`용 wheel만 존재하고 소스 배포판도 없어, Python 3.14에서는 설치 자체가 불가능하다.

`rag-api`/`rag-ent-api` 코드 문제가 아니라, `llama-index`가 사용하는 `tree-sitter-languages`가 아직 최신 Python(3.14)을 지원하지 않아 발생하는 환경 호환성 문제다.

**해결 방안**

`rag-ent-api` 프로젝트의 Python 버전을 3.12로 고정한다.

```bash
cd /Users/lemon/Devel/ai/rag-ent-api
rm -rf .venv
uv venv --python 3.12
source .venv/bin/activate
make install
```

**비고**

`tree-sitter-languages`가 Python 3.14 wheel을 배포하거나, `rag-api`가 `tree-sitter-language-pack` 등 유지보수 중인 대체 패키지로 마이그레이션하면 근본 해결된다.

---

## 8. 동일 문서 중복 처리 요청 시 모드별 회복 불가 케이스

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-07-04 |
| 심각도 | LOW |

**증상**

동일 문서(doc_id)에 대한 처리 요청이 이미 `status=running`인 문서에 다시 들어왔을 때, queue_worker/Dagster 두 모드 모두 자동으로는 회복 불가능한 케이스가 남아있다.

- **queue_worker 모드**: 실제로는 이미 죽었거나 끝난 작업인데 Postgres `status=running`만 남아있는 경우, 이 상태를 자동으로 감지/해소할 방법이 없어 해당 문서가 영원히 대기 상태로 남는다.
- **Dagster 모드**: `status=running, run_id=""`(QUEUED/STARTING 구간)에서 도착한 중복 이벤트는 중복 dispatch를 막기 위해 딜레이 재적재 없이 드롭된다([duplicate-request-handling.md](design/duplicate-request-handling.md) 3.2절, `_is_blocked_by_active_run()`에 구현 완료). 이 드롭 자체는 의도된 dedup 가드이지만, 두 가지 회복 불가 잔여 케이스가 남는다. (1) 드롭된 이벤트가 실제로는 콘텐츠 변경분이었다면 `content_version`(ETag)이 예전 버전 기준으로 남아 실제 S3 상태와 어긋날 수 있다. (2) `run_id`가 영원히 채워지지 않는 채로 남으면(Dagster 쪽 문제로 run이 QUEUED/STARTING을 못 벗어나는 경우), 그 문서에 대한 모든 후속 요청이 계속 드롭되기만 한다.

**원인**

- queue_worker: `run_id` 개념이 없어(항상 `"direct"` 상수) 작업이 실제로 살아있는지 확인할 방법이 Dagster처럼 GraphQL로 조회하는 식으로는 존재하지 않는다. 설령 수작업으로 `status`를 `failed`로 바꿔도(`POST /docs/{id}/fail`, `POST /docs/{id}/recover`), **ThreadPoolExecutor에서 실제로 그 작업이 끝났는지 확인/보장할 방법이 없다** — Python 스레드는 외부에서 안전하게 강제 종료하거나 생존 여부를 조회할 수 없기 때문이다.
- Dagster: `_is_blocked_by_active_run()`이 `run_id`가 없으면 드롭하도록 되어 있는데(중복 dispatch 방지를 위한 의도된 설계 — [duplicate-request-handling.md](design/duplicate-request-handling.md) 참조), 드롭된 이벤트가 실제로는 "콘텐츠가 바뀌어 재인덱싱이 필요하다"는 의미였을 경우 그 갱신 요청 자체가 사라져 ETag가 실제 S3 상태와 어긋난 채로 남는다. `run_id`가 채워지는 시점(`validate_op` 실행)까지 도달하지 못하고 계속 QUEUED/STARTING에 머무르는 경우(run launcher 문제, 리소스 부족 등)도 자동 감지 수단이 없다.

**현재 대안**

- queue_worker: 수작업으로 `POST /docs/{id}/fail` 또는 `POST /docs/{id}/recover` 호출 — DB 상태만 바꿀 뿐, 실제 스레드 생존 여부는 확인/보장 못 함.
- Dagster: Dagster 콘솔/GraphQL로 직접 run 상태를 확인해 수작업 처리. 타임아웃 기반 자동 판정은 미구현.

**해결 방안**

코드로 개선 가능한 영역은 **ETag 드리프트뿐**이다 — 구체적 방법은 아직 미정, 별도 논의 필요. 그 외(queue_worker의 영구 대기, Dagster의 run_id 영구 미기록, 스레드 생존 확인 불가)는 코드로 해결할 수 있는 영역이 아니며 수작업 개입 또는 운영 정책(타임아웃 값 도입 여부 등)으로만 대응 가능하다.

---

## 9. 커넥터 abort 시 센서 pop~RunRequest 구간의 서브초 레이스로 취소 대상 누락

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-07-04 |
| 심각도 | LOW |

**증상**

`POST /api/connectors/{id}/sync/abort` 요청이 센서 한 틱 안의 아주 짧은 순간과 겹치면, 해당
이벤트가 취소되지 않고 그대로 처리될 수 있다.

**원인**

`event_queue_sensor.py`가 Redis에서 이벤트를 pop하는 시점과 `RunRequest`를 yield하는 시점
사이에는 아주 짧은 간격이 있다. 이 구간에 abort가 끼어들면:

- Redis 큐에서는 이미 이벤트가 빠져나온 상태라 `dequeue_upload_events()`로 제거할 수 없고
- Dagster run은 아직 생성되지 않은 상태라 `terminate_dagster_run()` /
  `find_active_run_ids_by_doc_ids()`로도 종료 대상을 찾을 수 없다

즉 "취소할 대상 자체가 없는" 상태가 발생한다. 센서를 트랜잭션화(pop과 yield를 원자적으로 묶음)
하지 않는 한 근본적으로 막을 수 없는 서브초 단위 레이스다.

**현재 대안**

없음. 발생 빈도가 극히 낮고(서브초 윈도우), 발생해도 해당 문서 하나가 abort 요청에도 불구하고
정상 처리되는 정도로 영향이 그치며(데이터 정합성 문제는 아님) 별도 대응 없이 known limitation으로
남긴다.

**미해결**

센서를 트랜잭션화하지 않는 한 해결 불가. US-34에서 해결 범위 밖으로 명시했다
(`.claude/backlogs/US-34-connector-abort-missed-queued-run.md` "Known Limitation" 절 참조).