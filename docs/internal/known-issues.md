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
  - [7. tree-sitter-languages가 Python 3.13+ 미지원 — rag-ent-api install 실패, rag-api pyproject.toml도 상한 없음](#7-tree-sitter-languages가-python-313-미지원--rag-ent-api-install-실패-rag-api-pyprojecttoml도-상한-없음)
  - [8. 동일 문서 중복 처리 요청 시 모드별 회복 불가 케이스](#8-동일-문서-중복-처리-요청-시-모드별-회복-불가-케이스)
  - [9. 커넥터 abort 시 센서 pop~RunRequest 구간의 서브초 레이스로 취소 대상 누락](#9-커넥터-abort-시-센서-poprunrequest-구간의-서브초-레이스로-취소-대상-누락)
  - [10. Confluence 커넥터 첨부파일 목록 조회 네트워크 오류가 API/DB 어디에도 남지 않음](#10-confluence-커넥터-첨부파일-목록-조회-네트워크-오류가-apidb-어디에도-남지-않음)
  - [11. dagster-rag-api 코드서버가 잘못된 command로 기동 즉시 종료](#11-dagster-rag-api-코드서버가-잘못된-command로-기동-즉시-종료)
  - [12. /ready의 동기 블로킹 ping이 단일 이벤트 루프를 점유해 /health 등 무관한 요청까지 지연](#12-ready의-동기-블로킹-ping이-단일-이벤트-루프를-점유해-health-등-무관한-요청까지-지연)
  - [13. SimHash stage1 'similar' 판정이 stage2(MinHash) 확인 없이 바로 커밋됨](#13-simhash-stage1-similar-판정이-stage2minhash-확인-없이-바로-커밋됨)
  - [14. chunk_compare(dedup 3단계) 도입 시 신규 문서 A의 청크·임베딩 이중 계산](#14-chunk_comparededup-3단계-도입-시-신규-문서-a의-청크임베딩-이중-계산)
  - [15. Reindex 시 SimHash/MinHash 후보 조회가 status='indexed'만 대상으로 하여 outdated 문서 방향 탐지 불가](#15-reindex-시-simhashminhash-후보-조회가-statusindexed만-대상으로-하여-outdated-문서-방향-탐지-불가)
  - [16. Dagster 컨테이너 강제 중단 시 STARTING 상태 run이 재시작 후에도 영구히 STARTING에 남음](#16-dagster-컨테이너-강제-중단-시-starting-상태-run이-재시작-후에도-영구히-starting에-남음)
  - [17. 위키형 페이지에서 trafilatura favor_precision이 본문 90%+ 손실](#17-위키형-페이지에서-trafilatura-favor_precision이-본문-90-손실)

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

## 7. tree-sitter-languages가 Python 3.13+ 미지원 — rag-ent-api install 실패, rag-api pyproject.toml도 상한 없음

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-07-03 |
| 심각도 | LOW |

**증상**

두 가지 증상이 같은 원인에서 나온다.

1. `rag-ent-api`에서 `make install`(`uv sync`) 실행 시 실패한다 (uv가 Python 3.14를 선택하는 경우).
2. `rag-api` 자신의 [`pyproject.toml:4`](../../pyproject.toml#L4)도 `requires-python = ">=3.11"`에
   상한이 없어, 3.13+로 직접 `uv venv`/`uv sync`를 실행하면 `rag-api`만 단독으로 설치해도 동일하게
   깨진다. 지금 문제가 안 보이는 건 저장소 루트의 [`.python-version`](../../.python-version)(`3.12`)과
   [`Dockerfile:1`](../../Dockerfile#L1)의 `FROM python:3.12-slim`이라는 관례적 핀 두 개 덕분일
   뿐이다 — `pyproject.toml` 메타데이터 자체는 3.13/3.14 설치를 막지 않는다.

**원인**

1. `rag-api`는 코드 청킹에 [`chunk.py`](../../src/rag_api/pipeline/ops/chunk.py)의
   `_build_code_parser()`를 통해 `llama_index.core.node_parser.CodeSplitter`를 사용한다.
2. `CodeSplitter`는 내부적으로 `tree-sitter-languages` 패키지에 의존한다
   ([pyproject.toml:37-38](../../pyproject.toml#L37-L38)).
3. `tree-sitter-languages==1.10.2`(최신 버전, 2024-02 이후 업데이트 없음)는 `cp311`/`cp312`용
   wheel만 존재하고 소스 배포판도 없어, Python 3.13+ 에서는 설치 자체가 불가능하다.
4. `rag-ent-api`는 `../rag-api`를 editable 의존성으로 물고 있는데, `uv`가 `rag-ent-api`의
   가상환경 Python 버전을 독자적으로 resolve하면서(3.14 선택) 위 제약을 그대로 상속한다.
   `.python-version` 핀은 해당 디렉터리에서 직접 `uv venv`/`uv sync`를 실행할 때만 적용되고,
   다른 프로젝트가 editable/path 의존성으로 물어 자체 Python 버전을 resolve하는 경우에는 적용되지
   않는다. CI 워크플로도 없어(`.github/` 부재) 이를 강제하는 두 번째 안전장치도 없다.

`rag-api`/`rag-ent-api` 코드 문제가 아니라, `llama-index`가 사용하는 `tree-sitter-languages`가
아직 최신 Python(3.13+)을 지원하지 않아 발생하는 환경 호환성 문제다.

**현재 대안**

- `rag-ent-api`: 프로젝트의 Python 버전을 3.12로 고정한다.

  ```bash
  cd /Users/lemon/Devel/ai/rag-ent-api
  rm -rf .venv
  uv venv --python 3.12
  source .venv/bin/activate
  make install
  ```

- `rag-api`: 저장소 루트의 `.python-version`(3.12)과 `Dockerfile`의 `python:3.12-slim` 핀에
  의존해 현재는 문제없이 돌아간다. 다만 이는 관례적 핀일 뿐 `pyproject.toml` 메타데이터가 강제하는
  게 아니라서, 3.13+로 직접 venv를 만들면 여전히 깨진다.

**미해결**

`rag-api`의 `pyproject.toml`에 `requires-python = ">=3.11,<3.13"`처럼 명시적 상한을 선언하면
`uv`/`pip`가 호환되지 않는 Python 버전에서는 처음부터 설치를 거부하게 만들 수 있지만, 아직
반영되지 않았다. 근본 해결은 `tree-sitter-languages`가 최신 Python wheel을 배포하거나, `rag-api`가
유지보수 중인 대체 패키지(`tree-sitter-language-pack` 등)로 마이그레이션하는 것.

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

---

## 10. Confluence 커넥터 첨부파일 목록 조회 네트워크 오류가 API/DB 어디에도 남지 않음

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-07-04 |
| 심각도 | LOW |

**증상**

실 운영 로그에서 다음과 같은 패턴이 관측됨:

```
ERROR rag_api.connectors.confluence: Failed to list attachments for page: page_id=30760077 err=[Errno -3] Temporary failure in name resolution
INFO  rag_api.connectors.confluence: Confluence sync aborted: connector_id=3366226e307e45a4
INFO  rag_api.connectors.confluence: Confluence sync done: connector_id=3366226e307e45a4 space=KAFKA pages=44 max_pages=100
```

특정 페이지의 첨부파일 목록을 가져오다 DNS 조회 실패 등 네트워크 오류가 발생해도 sync 전체는
계속 진행되며, 실패 사실이 로그에만 남고 `documents` row나 커넥터 `last_error`
(`design/connector-state-flow.md` 참조 — 최근 도입된 필드지만 이 실패 경로는 반영 대상이 아님)
등 API로 조회 가능한 어디에도 기록되지 않는다.

**원인**

`ConfluenceConnector._process_page_attachments()`([confluence.py:262-276](../../src/rag_api/connectors/confluence.py#L262-L276))가
첨부파일 목록 조회(`_iter_attachments`) 전체를 `try/except Exception`으로 감싸고 `logger.error()`만
호출한 뒤 다음 페이지로 넘어간다. 이 시점에는 아직 개별 첨부파일에 대한 `documents` row가
생성되기 전이므로(row 생성은 `_process_attachment()` 내부, 목록 조회 성공 이후 단계) 실패를
기록할 대상 자체가 없다.

**현재 대안**

일회성 네트워크 장애(DNS 일시 실패 등)라면 자연히 복구됨 — "페이지 unchanged" 분기
(`confluence.py:189-192`)가 페이지 버전이 그대로여도 첨부파일은 매 sync마다 무조건 다시
나열하므로, 다음 sync 실행 시 같은 페이지의 첨부파일이 자동으로 재시도된다. 데이터가
영구 유실되지는 않는다.

**미해결**

특정 페이지에서 이 오류가 매 sync마다 반복되는 경우(예: 페이지별 권한 문제, 잘못된 URL 등
일회성이 아닌 원인)를 감지할 방법이 없다 — 로그를 grep하지 않는 한 아무도 알아채지 못한다.
개선하려면 연속 실패 횟수를 페이지 단위로 추적하거나, 실패를 커넥터 `last_error`에 경고로
남기는 방식이 필요하나 아직 미구현.

---

## 11. dagster-rag-api 코드서버가 잘못된 command로 기동 즉시 종료

| 항목 | 내용 |
|------|------|
| 상태 | resolved |
| 발견일 | 2026-07-05 |
| 해결일 | 2026-07-05 |
| 심각도 | HIGH |

**증상**

`dagster-daemon` 로그에 다음 경고가 반복 출력되고, 센서/스케줄이 전혀 실행되지 않음:

```
UserWarning: Error loading repository location grpc:dagster-rag-api:4000:
dagster._core.errors.DagsterUserCodeUnreachableError: Could not reach user code server.
gRPC Error code: UNAVAILABLE
```

`docker logs dagster-rag-api`에는 다음이 남고 컨테이너가 즉시 종료(exit code 2)됨:

```
Usage: dagster code-server start [OPTIONS]
Try 'dagster code-server start --help' for help.
Error: Got unexpected extra argument (rag_api.defs.definitions)
```

**원인**

`docker/docker-compose.yml`의 `dagster-rag-api.command`를 파일 모드(`-f
src/rag_api/defs/definitions.py`)에서 모듈 모드(`-m rag_api.defs.definitions`)로 바꾸는
과정에서 값이 빠진 `-f` 플래그가 남아 있었다:

```
dagster code-server start -h 0.0.0.0 -p 4000 -f  -m rag_api.defs.definitions
```

`-f`가 빈 값을 삼키면서 `-m rag_api.defs.definitions`가 예상치 못한 위치 인자로 파싱되어
프로세스가 기동 직후 종료됐다.

**해결**

`docker/docker-compose.yml:44`에서 불필요한 `-f`를 제거:

```
command: dagster code-server start -h 0.0.0.0 -p 4000 -m rag_api.defs.definitions
```

`docker compose up -d dagster-rag-api`로 재기동 후 코드서버 정상 기동 및 `dagster-daemon`의
센서 폴링 재개를 확인함.

---

## 12. /ready의 동기 블로킹 ping이 단일 이벤트 루프를 점유해 /health 등 무관한 요청까지 지연

| 항목 | 내용 |
|------|------|
| 상태 | resolved |
| 발견일 | 2026-07-06 |
| 해결일 | 2026-07-06 |
| 심각도 | MEDIUM |

**증상**

rag-ent-api 쪽에서 10명 동시 사용자 조회 부하 테스트를 진행하던 중, `/ready`를 50개
동시 호출하는 시나리오에서 latency가 순차 호출(p50 63~93ms) 대비 크게 상승(p50 530ms,
max 587ms)했다. 별도로 `/ready` 폭주 중 무관한 `/health`를 인터리빙해서 찔러본 결과, 평소
1ms 미만이던 `/health`가 폭주 중에는 최대 490.7ms까지 튀었다 — `/health`는 `/ready`와
아무 관련이 없어야 하는 요청인데도 지연이 전이됨. 자세한 재현 과정은 rag-ent-api 저장소의
`docs/internal/testing/concurrent-read-load-test-results.md` §3 참고.

**원인**

`api/routers/health.py`의 `readiness()`에서 S3 체크(`_s3_ok()`)는 `asyncio.to_thread`로
이벤트 루프 밖 스레드에서 실행되도록 되어 있었지만, `qdrant_ping()`/`redis_ping()`/
`postgres_ping()`은 `async def readiness()` 안에서 **동기 블로킹 호출로 직접** 실행되고
있었다. 이 서비스는 uvicorn을 단일 워커(이벤트 루프 1개)로 띄우므로, 이 블로킹 호출들이
실행되는 짧은 시간 동안은 `/ready`뿐 아니라 그 순간 도착한 다른 모든 요청까지 이벤트 루프에서
함께 대기해야 한다. `/ready`는 `exempt_paths`(rate limit 미적용)라 호출 빈도 제한이 없어,
반복 호출(실수 또는 악의적)이 서비스 전체 응답성에 영향을 줄 수 있는 벡터였다. E-17
(rag-ent-api, Redis 소켓 타임아웃 미설정으로 인한 이벤트 루프 정지)과 같은 계열의 문제다.

**해결**

`_s3_ok()`와 동일한 패턴을 공통 헬퍼로 추출해 세 ping에도 동일하게 적용했다 (`ping()`
함수를 인자로 전달받아 반복을 없앰):

```python
async def _ping_ok(name: str, fn: Callable[[], bool]) -> bool:
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=5)
    except TimeoutError:
        logger.error("Readiness check timed out: %s", name)
        return False
```

```python
checks: dict[str, bool] = {
    "qdrant": await _ping_ok("qdrant", qdrant_ping),
    "redis": await _ping_ok("redis", redis_ping),
    "postgres": await _ping_ok("postgres", postgres_ping),
    "s3": await _s3_ok(),
}
```

**재검증**

동일한 50-동시 `/ready` 시나리오 + `/health` 인터리빙 테스트를 서버 재시작 후 재실행:

| 지표 | 수정 전 | 수정 후 |
|---|---|---|
| `/ready` 50 동시 p50 | 530.3ms | 442.0ms |
| `/health` 폭주 중 최대 스파이크 | 490.7ms | 266.8ms |
| `/health` 폭주 중 p50 | 7.2ms | 4.9ms |

다른 엔드포인트로의 지연 전이는 뚜렷이 감소(최대 스파이크 46%↓)했다. `/ready` 자체의 절대
latency가 크게 줄지 않은 것은, 이제 이벤트 루프 대신 스레드풀(`asyncio.to_thread` 기본
executor)에서 50×3개 ping이 경합하기 때문으로 추정되며, 이는 실제 다운스트림 동시 접속
비용이지 이벤트 루프 블로킹 버그가 아니므로 훨씬 덜 심각하다.

**비고**

`ping()` 함수들(`infra/qdrant.py`, `infra/redis.py`, `infra/postgres.py`)은 이미 내부에서
예외를 잡아 로그를 남기고 `bool`을 반환하므로, `_ping_ok()`는 스레드 실행과 타임아웃만
책임진다 — `ping()` 자체의 예외 처리 정책은 변경하지 않았다.

---

## 13. SimHash stage1 'similar' 판정이 stage2(MinHash) 확인 없이 바로 커밋됨

| 항목 | 내용 |
|------|------|
| 상태 | resolved |
| 발견일 | 2026-07-07 |
| 해결일 | 2026-07-09 |
| 심각도 | MED |

**증상**

서로 무관한 두 Kubernetes 공식 문서(둘 다 Security 카테고리: "API Server Bypass Risks",
"Security Checklist")를 인제스트하면, stage 1(SimHash) Hamming distance가 8~10 사이로 나와
`body_match="similar"`로 분류된다(`hamming_identical_threshold=3` 초과,
`hamming_similar_threshold=10` 이하). 이 판정은 stage 2(MinHash) 확인을 전혀 거치지 않고
바로 `handle_similar()`로 전달되어, 두 문서 중 하나가 강제로 outdated 처리(색인 안 됨)되거나
상대 문서의 기존 Qdrant 청크가 삭제될 수 있다.

**원인**

`run_dedup_pipeline`([dedup/**init**.py:79-82](../../src/rag_api/pipeline/ops/dedup/__init__.py#L79-L82))은
stage 1 결과 `body_match == "none"`일 때만 stage 2(MinHash)를 실행한다. `"similar"`
(Hamming distance가 identical_threshold~similar_threshold 사이)와 `"identical_level"`
둘 다 stage 2 확인 없이 즉시 `run_verdict`로 넘어가며, `"similar"`는
`handle_similar()`([verdict.py:109-143](../../src/rag_api/pipeline/ops/dedup/verdict.py#L109-L143))를
통해 파괴적 액션(청크 삭제/색인 스킵)을 수행한다.

SimHash([simhash.py:26-48](../../src/rag_api/pipeline/ops/dedup/simhash.py#L26-L48), 문자
3-gram, 64bit)는 텍스트 길이·어휘 중복에 민감한 성긴(coarse) 신호라, 같은
카테고리/주제의 문서끼리는 실제 중복이 아니어도 "similar" 밴드에 쉽게 들어갈 수 있다.

**모의 테스트로 확인한 사실**

처음에는 `HTMLCleanReader`(`pipeline/ops/parse.py`)가 사이트 공통 boilerplate(`#pre-footer`
Feedback 블록 등, nav/header/footer/aside 태그로 감싸지지 않아 stripping 대상에서 빠짐)를
제거하지 못해 생기는 파싱 문제로 의심했으나, 실제 프로젝트 코드(`compute_simhash`,
`hamming_distance`, `compute_minhash`, `compute_jaccard`)로 두 문서의 `<main>` 본문에 대해
`#pre-footer` 제거 전/후를 비교한 결과:

| | Hamming distance | Jaccard(MinHash) |
|---|---|---|
| 현재 상태(`#pre-footer` 등 boilerplate 포함) | 8 | 0.258 |
| `#pre-footer` div 제거 후 | 10 | 0.234 |
| 임계값 | identical≤3 / similar≤10 | jaccard_threshold=0.65 |

boilerplate를 제거해도 Hamming distance는 오히려 늘었고(8→10) 여전히 "similar" 밴드 안에
머물렀다. 반면 Jaccard는 boilerplate 유무와 무관하게 0.234~0.258로 threshold(0.65)에 한참
못 미쳐, stage 2가 실행됐다면 두 문서를 정확히 "다른 문서"로 판별했을 것이다. 즉 오탐의
원인은 파싱 잔여물이 아니라 stage 1의 coarse한 특성 + 동일 카테고리 어휘 중복이며, 실제
리스크는 stage 2 미실행 쪽에 있다.

**현재 동작**

`"similar"` 판정 시 `handle_similar()`가 `_resolve_newer()`로 두 문서 중 어느 쪽이 최신인지
비교해, incoming이 더 최신이면 기존 문서의 Qdrant 청크를 삭제하고 기존 문서를 outdated
처리, incoming이 더 오래됐으면 incoming 자체를 색인하지 않고 outdated 처리한다. 두 경우
모두 stage 2 확인 없이 실행된다.

**해결**

당초 제안(stage 2 MinHash로 재확인)은 US-35(chunk_compare, dedup 3단계) 구현으로 대체되어
해소되었다. `body_match == "similar"`(simhash 또는 minhash 단계 산출)는 이제 즉시 verdict로
커밋되지 않고, `run_chunk_compare()`([chunk_compare.py](../../src/rag_api/pipeline/ops/dedup/chunk_compare.py))가
청크 단위 임베딩 코사인 유사도로 문서 레벨 집계 점수를 산출해 `body_identical_threshold`(0.95)/
`body_similar_threshold`(0.75) 임계값으로 body(identical_level/similar/none)를 재확정한 뒤에야
`run_verdict()`로 넘어간다(`pipeline/ops/dedup/__init__.py`의 `run_dedup_pipeline()` 라우팅 참고).
MinHash(stage 2)가 아닌 더 정밀한 임베딩 비교로 재확인이 이뤄지므로 원래 제안보다 강한 형태로
해결되었다고 판단.

---

## 14. chunk_compare(dedup 3단계) 도입 시 신규 문서 A의 청크·임베딩 이중 계산

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-07-09 |
| 심각도 | LOW |

**증상**

dedup 3단계(chunk_compare, `.claude/backlogs/todo/US-35-dedup-stage3-chunk-compare.md`, 아직
미구현)가 도입되면, simhash/minhash 단계에서 `body_match="similar"`로 라우팅된 문서 A는 dedup
판정을 위해 `chunk()`+`embed()`로 청크·임베딩을 즉석 계산한다(Qdrant에는 저장하지 않고 검색
쿼리 벡터로만 사용). 이후 verdict가 `proceed`(무관)로 확정되어 `needs_indexing=True`가 되면,
표준 파이프라인(`chunk_op` → `embed_op` → `upsert_op`)이 동일한 A 문서를 처음부터 다시
청크·임베딩한다. 이 경로를 타는 문서는 임베딩 계산이 정확히 두 번 발생한다.

**원인**

`ingest_job`은 `parse_op → dedup_op → chunk_op` 순서로 고정되어 있어, dedup_op(chunk_compare
포함)이 A를 Qdrant에 색인하기 전 단계에서 실행된다. dedup_op과 표준 색인 파이프라인은 서로 다른
op으로 분리돼 있어, chunk_compare가 계산한 청크/임베딩 결과를 이후 `chunk_op`/`embed_op`가
재사용하려면 별도의 op 간 결과 전달·캐싱 메커니즘이 필요하다.

**현재 대안/결정**

캐싱은 도입하지 않기로 결정(2026-07-09) — 이중 계산 비용(임베딩 API 호출 2회)을 감수한다.
근거: chunk_compare는 `body_match="similar"`로 좁혀진 후보에만 실행되므로(identical/none
경로는 애초에 해당 없음) 전체 인제스트 대비 발생 빈도가 낮고, 캐싱 메커니즘(op 간 결과 전달,
무효화, 메모리 사용량) 도입 복잡도가 절감되는 비용 대비 크다고 판단.

**미해결**

인제스트 볼륨이 커지고 similar 판정 비율이 높아지면 재검토 필요. 그 경우 dedup_op과 chunk_op을
하나의 op으로 합쳐 청크/임베딩 결과를 직접 전달하는 방식을 고려할 수 있음(파이프라인 구조 변경
필요, 별도 논의 대상).

---

## 15. Reindex 시 SimHash/MinHash 후보 조회가 status='indexed'만 대상으로 하여 outdated 문서 방향 탐지 불가

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-07-09 |
| 심각도 | LOW |

**증상**

문서 A(예: README-2.md, 이미 `outdated`, `duplicate_of=B`)가 문서 B(예: README.md, `indexed`)의
근접 중복으로 판정되어 outdated 처리된 상태에서, A를 reindex하면 B를 후보로 정상 발견해
chunk_compare까지 도달하지만(재확인 후 outdated 유지), 반대로 B를 reindex하면 A를 후보로 전혀
발견하지 못하고 simhash/minhash 모두 "무관"(`none`)으로 판정되어 chunk_compare 자체가 호출되지
않는다(`run_dedup_pipeline`의 `if result.body_match == "similar":` 라우팅 조건이 성립하지 않음).

**원인**

`infra/postgres.py`의 후보 조회 함수(`find_simhash_candidates:755`, `find_minhash_candidates:837`,
`find_title_candidates:874`) 전부 `WHERE ... d.status = 'indexed'` 조건으로 필터링한다.
`outdated` 상태인 문서는 simhash_bands/minhash_bands에 값이 남아 있어도(또는 애초에 저장 자체가
안 됐어도, simhash 단계는 `body_match == "none"`일 때만 저장하므로) 어떤 문서로부터도 후보로
조회되지 않는다.

결과적으로 두 문서 간 중복 관계가 한 번 `indexed`/`outdated`로 확정되면, `outdated` 쪽만 계속
`indexed` 쪽을 찾아낼 수 있고 반대 방향은 구조적으로 불가능하다. 어느 쪽이 `indexed`로 남는지는
최초 인제스트 순서와 `_resolve_newer()`(`verdict.py`)의 신구 판단 결과에 좌우되므로, 동일한 두
문서라도 인제스트 순서가 바뀌면 관찰되는 비대칭 방향도 반대로 나타난다.

**현재 동작**

`indexed` 상태 문서를 수동 reindex하면 이미 확정된 outdated 관계를 재확인하지 않고 항상
"무관"으로 진행되어 chunk_compare를 거치지 않는다. 색인 자체는 정상 완료되며 데이터 정합성
문제는 없다 — 이미 `outdated`로 확정된 문서는 검색에서 제외되므로 중복 노출도 없다.

**현재 대안/판단**

이 필터(`status='indexed'`만 후보 대상)는 의도된 설계로 보인다 — 이미 superseded된 문서를 새
인입 문서의 후보로 다시 끌어들이지 않기 위함. 부작용으로 "이미 승자로 확정된 문서"의 reindex는
항상 무관 판정으로 빠지는데, 그 문서 입장에서는 이미 관계가 확정되어 있어 재확인이 불필요하므로
실질적 문제로 이어지지는 않는다(2026-07-09 확인 — 논리적으로 기대되는 동작).

코드 변경 없이 관계를 재검증하고 싶다면, 해당 `indexed` 문서를 reindex하는 대신 삭제 후
재업로드한다(운영 워크어라운드). 삭제 시점에 문서가 코퍼스에서 완전히 빠지고, 재업로드는 신규
인제스트로 처리되어 dedup 파이프라인이 처음부터 다시 수행된다.

**미해결**

`indexed` 문서를 reindex할 때 이미 자신을 `duplicate_of`로 참조하는 `outdated` 문서들과의 관계를
재검증해야 하는 시나리오(예: 운영자가 dedup 임계값 변경 후 기존 관계를 재검증하고 싶은 경우)가
생기면, 후보 조회에 status 필터를 완화하거나 `duplicate_of` 역참조 조회를 별도로 추가하는 방안을
검토해야 한다. 현재는 별도 조치 없음(워크어라운드로 대체 가능).

---

## 16. Dagster 컨테이너 강제 중단 시 STARTING 상태 run이 재시작 후에도 영구히 STARTING에 남음

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-07-10 |
| 심각도 | MED |

**증상**

job이 `STARTING` 상태인 도중 Dagster 컨테이너(daemon 또는 code-server)를 강제로 중단하면 실행
중이던 프로세스가 사라진다. 컨테이너를 다시 시작해도 해당 run은 자동으로 정리되지 않고 `STARTING`
상태에 영구히 남아, 이후 같은 문서/커넥터에 대한 신규 요청이 계속 막히거나 중복 처리 가드에 걸릴
수 있다.

**원인**

컨테이너를 강제 종료하면 run을 실제로 실행하던 프로세스는 죽지만, run storage(Postgres)에 남아
있는 run record는 `STARTING`(또는 `STARTED`) 그대로 유지된다. `docker/dagster.yaml`에는 이미
`run_monitoring`이 설정되어 있다.

```yaml
run_monitoring:
  enabled: true
  poll_interval_seconds: 120
  max_resume_run_attempts: 0
```

설치된 Dagster 패키지 소스를 추적한 결과, 이 설정은 상태에 따라 동작 여부가 갈린다.

- **`STARTING` 상태**: `monitor_starting_run()`이 run launcher와 무관하게 `RUN_STARTING` 이벤트
  타임스탬프 기준 경과 시간만으로 판정한다(`start_timeout_seconds`, 기본값 180초 — 이 파일에도
  미설정이라 기본값 적용). 이론상 다음 poll 주기(최대 120초 뒤) 안에 자동으로 `report_run_failed()`가
  호출돼 정리돼야 한다.
- **`STARTED` 상태**: `monitor_started_run()`은 (1) `run_launcher.check_run_worker_health()`와
  (2) `max_runtime_seconds` 두 경로로만 죽은 워커를 감지하는데, 이 저장소는 `run_launcher`를
  명시하지 않아 기본값인 `DefaultRunLauncher`가 쓰인다. 이 launcher는
  `check_run_worker_health()`를 아예 지원하지 않고(`NotImplementedError`), `max_runtime_seconds`도
  미설정(기본 0, 비활성)이다. **즉 run이 일단 `STARTED`로 넘어간 뒤 워커 프로세스가 죽으면 두
  경로 다 막혀 있어 run_monitoring이 전혀 감지하지 못한다.**

코드상 `STARTING` 자체는 자동 정리돼야 하므로, 실제로 "영원히 STARTING에 남는" case는 (a) 이미
`STARTED`로 넘어간 뒤 죽어서 위 gap에 해당하거나, (b) 모니터링이 해당 run에서 매 poll마다
예외를 던져(내부에서 잡고 로그만 남김) 정리가 계속 스킵되는 경우일 가능성이 높다.
`dagster-daemon` 로그에서 `Hit error while monitoring run <run_id>`를 검색하면 (b) 여부를 바로
확인할 수 있다.

정상적인 `terminate_dagster_run()` 경로([이슈 3](#3-커넥터-동기화-중단-불가) 참조)는 살아있는
프로세스에 SIGTERM을 보내는 방식이라, 프로세스 자체가 이미 사라진 이 케이스에는 애초에 적용되지
않는다.

**현재 대안**

- API 쪽에서 force abort(강제 실패 처리)를 호출하거나,
- Dagster 콘솔(Dagit UI)에서 해당 run을 직접 수동으로 terminate 해야 한다.

**미해결**

- `dagster-daemon` 로그에서 이 run에 대해 `Hit error while monitoring run`이 반복되는지 확인
  필요(위 4번 경로가 실제로 예외로 막히고 있는지 검증).
- `STARTED` 상태 이후의 워커 사망(3번 gap)에 대한 근본 대응은 두 가지 방향이 있고 아직 어느 쪽도
  적용되지 않았다:
  - `run_monitoring.max_runtime_seconds`(또는 run 태그 `dagster/max_runtime_seconds`)를 설정해
    최소한 "너무 오래 실행 중인 run"은 강제 timeout으로 정리되게 한다 — 다만 이는 죽은 워커
    감지가 아니라 실행 시간 상한이므로, 정상적으로 오래 걸리는 job과 구분이 안 되는 트레이드오프가
    있다.
  - run launcher를 `DockerRunLauncher`(run마다 별도 컨테이너로 실행, Docker API로 실제 컨테이너
    생존 여부를 확인 가능해 `check_run_worker_health`가 의미 있게 동작)로 교체한다 — 현재
    `DefaultRunLauncher`(code-server 프로세스의 subprocess로 실행)는 애초에 헬스체크 자체를
    지원하지 않아 이 설정만으로는 해결 불가능.
  - 둘 다 아직 백로그 미등록, 별도 논의 필요.

---

## 17. 위키형 페이지에서 trafilatura favor_precision이 본문 90%+ 손실

| 항목 | 내용 |
|------|------|
| 상태 | resolved |
| 발견일 | 2026-07-13 |
| 해결일 | 2026-07-13 |
| 심각도 | MED |

**증상**

kb-02 doc_id=`b950892c61d1463c`(namu.wiki "고양이" 문서)를 "최고령 고양이"로 검색해도 결과가
나오지 않았다. 실제로 인제스트된 9개 청크(총 7,813자)를 전부 확인해도 해당 텍스트가 없었다 —
임베딩 문제가 아니라 파싱 단계에서 이미 누락된 것이었다.

**원인**

`HTMLCleanReader`(`pipeline/ops/parse.py`)가 쓰는 trafilatura의 `favor_precision=True`(당시
기본값)는 "본문인지 애매한 블록"을 공격적으로 제외하는데, namu.wiki 특유의 각주/목차/접기박스
밀집 구조에서 실제 본문의 93% 이상을 "애매한 블록"으로 오판해 통째로 버렸다. 원문을
`favor_recall=True`로 재추출하면 104,952자가 나오는데, 실제 인제스트분은 7,813자뿐이었다.
"최고령 고양이" 섹션이 그 버려진 부분에 있어 청킹·임베딩 대상에 아예 포함되지 않았다.

**해결**

trafilatura 소스(`trafilatura/settings.py:143`)를 확인한 결과 `favor_precision`/`favor_recall`은
실제로는 `"recall" if recall else "precision" if precision else "balanced"` 순서로 평가되는
3단계 tri-state였다. US-39에서 이를 `settings.ingestion.html_extraction_mode`
(`precision`/`recall`/`balanced`)로 노출하고 기본값을 `recall`로 전환했다 — 동일 문서에서
`favor_recall=True`로 재추출 시 "최고령 고양이" 관련 실제 문장(코듀로이/밍키/프짱/스쿠터 기록)이
정상 포함됨을 확인. 상세 설계는
`docs/internal/design/html-extraction.md` §3.2 참고.

**`html_extraction_mode` 값별 동작**

| 값 | 판단 기준 | 트레이드오프 |
|----|-----------|--------------|
| `"precision"` | 애매하면 제외 | 본문 일부가 boilerplate로 오판되어 손실될 수 있음 — 위키형 페이지(namu.wiki 등)에서 본문 90%+ 손실 실측됨 |
| `"balanced"` | 표준 임계치, 모드 전용 로직 미적용 | precision/recall 중간값. 검증된 운영 데이터는 아직 없음 |
| `"recall"` (기본값) | 애매하면 포함 | 라이선스 푸터 등 짧은 boilerplate가 본문에 섞여 들어올 수 있음(실측 확인) — 그러나 본문 손실보다는 검색 가능성을 우선한 선택 |

**잔여 이슈**

- US-39 이전에 `precision` 모드로 이미 인제스트된 기존 HTML 문서는 자동으로 재추출되지
  않는다 — 재인제스트 필요 여부는 운영 판단 대상.
- `recall` 모드는 라이선스 푸터 같은 짧은 boilerplate가 본문에 섞여 들어올 수 있다는
  트레이드오프가 실측으로 확인됨(`docs/internal/design/html-extraction.md` §6 참고).
- `connectors/web.py`의 `_has_sufficient_content()`는 여전히 중립(`balanced`) 모드로
  trafilatura를 호출해 스테이징 여부를 판단한다 — 파싱 단계(`recall`)와 게이팅 단계
  (`balanced`)의 기준이 다른 비일관성은 이번 수정 범위 밖.