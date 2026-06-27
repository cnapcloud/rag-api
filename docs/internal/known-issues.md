# Known Issues

발견된 이슈를 기록하는 문서. 해결 시 상태를 `open` -> `resolved`로 변경하고 해결 방법을 기록한다.

---

## 목차

1. [DELETE /docs/{source} returns 200 for non-existent document](#1-delete-docssource-returns-200-for-non-existent-document)
2. [Dagster SensorDefinition owners parameter BetaWarning](#2-dagster-sensordefinition-owners-parameter-betawarning)
3. [커넥터 동기화 중단 불가](#3-커넥터-동기화-중단-불가)
4. [Delete + Reindex race condition](#4-delete--reindex-race-condition)
5. [SimHash/MinHash 동시 유사 문서 누락](#5-simhashminhash-동시-유사-문서-누락)

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

동기화는 FastAPI `BackgroundTask`(일반 Python 스레드)로 실행된다. 완전한 중단을 위해서는 세 가지를 동시에 처리해야 한다:

1. **커넥터 수집 루프 중단** — 파일 fetch 루프에 abort 플래그 체크 추가
2. **Redis 인제스트 큐에서 해당 커넥터 항목 제거** — Redis list는 특정 항목만 골라내는 atomic 연산이 없어 drain 후 재투입 방식만 가능
3. **Dagster 실행 대기(QUEUED) run 제거** — Dagster run queue에 쌓인 미시작 run을 GraphQL `deletePipelineRun()` 또는 `cancelPipelineRun()`으로 제거 필요
4. **실행 중인 Dagster job 취소** — GraphQL `terminateRun()` 호출 필요

**현재 대안**

`POST /api/connectors/{id}/sync/abort`로 수집 루프를 중단할 수 있다. 커넥터가 파일/URL을 처리할 때마다 abort 플래그를 확인하고 감지 시 즉시 루프를 종료한다. 단, 이미 Redis 큐에 투입된 문서는 Dagster가 계속 처리하며, Dagster에서 실행 중인 job은 별도로 취소되지 않는다.

**미해결**

2(Redis 큐 항목 제거), 3(Dagster 대기 run 제거), 4(실행 중 Dagster job 취소)는 미구현 상태.

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
