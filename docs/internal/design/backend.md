# Backend Design

내부 데이터 구조, 상태 정의, 시스템 흐름에 대한 설계 문서.
엔드포인트 계약(스키마, 파라미터)은 `/docs` (Swagger UI) 참고.
API 사용법(curl 예시)은 [guide/api-guide.md](../guide/api-guide.md) 참고.

---

## 목차

1. [문서 상태 (status)](#1-문서-상태-status)
2. [Redis 키 구조](#2-redis-키-구조)
3. [Qdrant Payload 스키마](#3-qdrant-payload-스키마)
4. [검색 흐름](#4-검색-흐름)
5. [HTTP 에러 코드](#5-http-에러-코드)
6. [Delay 큐 동작 원리](#6-delay-큐-동작-원리)
7. [Dagster sensor default_status 동작 원리](#7-dagster-sensor-default_status-동작-원리)
8. [Dagster 로깅 동작 원리](#8-dagster-로깅-동작-원리)
9. [Sensor vs validate_op 역할 분리](#9-sensor-vs-validate_op-역할-분리)
10. [문서 버전 관리 / ETag 처리](#10-문서-버전-관리--etag-처리)
11. [KB 삭제 데이터 정리 순서](#11-kb-삭제-데이터-정리-순서)
12. [LlamaIndex 활용 범위](#12-llamaindex-활용-범위)
13. [Dagster 정의 구조](#13-dagster-정의-구조)
14. [로컬 실행 구조](#14-로컬-실행-구조)

---

## 1. 문서 상태 (status)

| 값 | 의미 |
|----|------|
| `pending` | Redis 큐에 대기 중 (Worker/Sensor가 아직 미수령) |
| `running` | 파이프라인 처리 중 |
| `indexed` | 인덱싱 완료 |
| `failed` | 파이프라인 실패 |
| `deleting` | 삭제 진행 중 |

### 상태 전이

```
신규 업로드 / reindex 요청
  └─ pending
       └─ Worker/Sensor 수령 → running
            ├─ 성공 → indexed
            └─ 실패 → failed

running / deleting 중 동일 문서 재요청
  └─ Redis 큐에 이벤트 추가 (상태 변경 없음, 현재 처리 계속)
       └─ 현재 처리 완료 → indexed / failed
            └─ Worker가 대기 이벤트 수령 → pending → running

삭제 요청
  └─ deleting → (완료 시 Postgres 행 삭제)

recover API (status=running 전용)
  └─ running → failed → pending → running (재큐잉)
```

---

## 2. Redis 키 구조

Redis는 이벤트 큐 전용으로만 사용한다 (US-11 이후).
KB·문서 메타데이터는 Postgres `knowledge_bases` / `documents` 테이블로 이전됨.

```
rag:upload:queue   # 인제스트 이벤트 큐  (List, lpush / rpop)
rag:delete:queue   # 삭제 이벤트 큐     (List, lpush / rpop)
rag:upload:delay   # 인제스트 지연 큐    (Sorted Set, score=ready_at, member=payload JSON)
rag:delete:delay   # 삭제 지연 큐       (Sorted Set, score=ready_at, member=payload JSON)
```

큐 이벤트 JSON 구조:

```json
{ "doc_id": "a1b2c3d4e5f6g7h8", "force": false }
```

처리 중인 문서가 이미 `running / deleting` 상태이면 delay 큐(Sorted Set)로 밀린다. 동작 원리는 [섹션 6](#6-delay-큐-동작-원리) 참고.

---

## 3. Qdrant Payload 스키마

```python
{
    "kb_id":              str,   # "kb-01"
    "doc_key":            str,   # "{kb_id}::{doc_source}"
    "doc_type":           str,   # "pdf" | "docx" | "txt" | "md" | "hwp"
    "doc_source":         str,   # "doc.pdf"
    "chunk_index":        int,
    "page_num":           int | None,
    "total_chunks":       int,
    "text":               str,
    "embedding_model":    str,   # "bge-m3"
    "embedding_provider": str,   # "ollama" | "openai"
    "chunk_strategy":     str,   # "recursive" | "semantic"
    "chunk_size":         int,
    "chunk_overlap":      int,
    "updated_at":         str,   # ISO 8601 UTC, 인덱싱 시각
    "doc_created_at":     str,   # ISO 8601 UTC, 문서 실제 생성일 (US-10, 없으면 빈 문자열)
}
```

컬렉션 구성: Dense (`cosine`) + Sparse (`IDF modifier`)

---

## 4. 검색 흐름

```
POST /api/search
    │
    ├─ KB별 병렬 Hybrid Search (Qdrant Dense + Sparse)
    │
    ├─ 복수 KB 결과 RRF 머지
    │
    ├─ Reranker (Jina) — enabled=true인 경우
    │       실패 시 → RRF 스코어 순 fallback
    │
    └─ top_n 반환
```

---

## 5. HTTP 에러 코드

| Status | 예외 클래스 | 발생 조건 |
|--------|-------------|-----------|
| 404 | `NotFoundError` | KB 또는 문서 없음 |
| 409 | `ConflictError` | 이미 존재하는 KB, 복구 불가 상태 |
| 422 | `IngestValidationError` | 파일 크기 초과, 지원하지 않는 형식 |
| 500 | `ConfigError` | 설정 오류 (vector_size 불일치 등) |
| 502 | `botocore.exceptions.ClientError` | S3 연결 실패 |
| 503 | `redis.RedisError` | Redis 연결 실패 |
| 503 | `psycopg.Error` | Postgres 연결 실패 |

---

## 6. Delay 큐 동작 원리

main 큐에서 꺼낸 이벤트의 문서가 `running / deleting` 상태이면 즉시 처리하지 않고
Redis Sorted Set으로 구성된 delay 큐에 넣는다.
score는 `time.time() + retry_interval_sec` (처리 가능 시각).

```
rpop rag:upload:queue
  └─ status=running / deleting
      → zadd rag:upload:delay  {payload: ready_at}

poll 시작 시:
  zrangebyscore rag:upload:delay 0 now
      → zrem (delay 큐에서 제거)
      → lpush rag:upload:queue (main 큐로 복원)
```

`retry_interval_sec`는 `settings.yaml`의 `queue_poll.retry_interval_sec`으로 설정.

### 중복 요청 overwrite

ZADD의 member key는 원본 payload JSON 문자열 (`{"doc_id": "...", "force": false}`)이다.
같은 doc_id + 같은 force 값이면 member가 동일하므로 ZADD가 score만 갱신한다 (overwrite).
동일 문서가 여러 번 block되더라도 delay 큐에 entry가 누적되지 않는다.

단, force 값이 다른 두 요청(예: `force:false`와 `force:true`)은 member가 달라 각각 독립 entry로 존재한다.

### sensor vs QueueWorker

| 항목 | event_queue_sensor | QueueWorker |
|------|-------------------|-------------|
| block 판단 | Dagster run_id 조회 (active run 확인) | doc status 확인 (running/deleting) |
| delay 방식 | zadd rag:upload:delay | zadd rag:upload:delay |
| drain 시점 | 매 sensor firing 시작 시 | 매 poll 시작 시 |

---

## 7. Dagster sensor default_status 동작 원리

`event_queue_sensor`는 `default_status=DefaultSensorStatus.RUNNING`으로 선언되어 있다.

- 이 값은 센서가 Dagster DB에 **처음 등록될 때만** 적용된다.
- 한 번 저장된 상태는 재배포나 재시작으로 바뀌지 않는다.
- STOPPED로 바뀌는 경우는 수동 stop 또는 DB 초기화뿐이다.

DB 초기화 후 재배포하면 신규 등록으로 처리되어 자동으로 RUNNING 상태가 된다.

---

## 8. Dagster 로깅 동작 원리

`pipeline/ops/` 순수 함수들은 `logging.getLogger(__name__)`을 사용한다.
Dagster는 기본적으로 이 로거를 감시하지 않으므로 Dagster UI에 로그가 나타나지 않는다.

`dagster.yaml`의 `managed_python_loggers`에 등록하면 Dagster UI에서도 볼 수 있다.

| 방식 | Dagster UI 노출 | 사용 위치 |
|------|----------------|-----------|
| `context.log.info()` | 항상 | Dagster op 래퍼 (`defs/ops/`) |
| `logging.getLogger(__name__)` 기본 | X | 순수 함수 (`pipeline/ops/`) |
| `logging.getLogger(__name__)` + `managed_python_loggers` | O | 순수 함수, 설정 후 |

---

## 9. Sensor vs validate_op 역할 분리

sensor는 큐 레벨에서 "언제 실행할지"를 결정하고, validate_op는 job 레벨에서 "파일 자체가 유효한지"를 검증한다.

### sensor (`event_queue_sensor.py`)

dispatch 결정 + dispatch lock 설정 + zombie 복구

```
Redis 큐에서 이벤트 pop
  └─ status=deleting          → delay queue로 밀기
  └─ status=running, run_id != ""
      ├─ Dagster run 살아있음  → delay queue로 밀기
      └─ Dagster run 죽었음   → set_failed() (zombie 복구) → dispatch 진행
  └─ status=running, run_id=""
      → dispatch lock 잔류로 간주, dispatch 진행

set_processing(kb_id, key, etag=etag)   # run_id="" 로 dispatch lock 기록
yield RunRequest(ingest_job)
```

### validate_op (`ingest_ops.py`)

run_id 등록 + 비즈니스 검증

```
set_processing(kb_id, key, etag=etag, run_id=context.run_id)
  # sensor가 ""로 남긴 run_id를 실제 Dagster run_id로 갱신

validate()
  ├─ ETag 중복 체크 (force=False이면 스킵)
  └─ 파일 크기 제한 체크

검증 통과  → Output 발행 → parse_op → chunk_op → ...
ETag 동일  → restore_indexed() (status=indexed 복원) → 이후 op 스킵
검증 실패  → set_failed() + 예외 raise
```

### 역할 경계 요약

| | sensor | validate_op |
|---|---|---|
| 책임 | dispatch 가부 결정 | 인제스트 가부 결정 |
| zombie 복구 | O (run_id 있는 경우만) | X |
| dispatch lock | `set_processing(run_id="")` | `set_processing(run_id=<실제값>)` 으로 갱신 |
| ETag 중복 체크 | X | O |
| 파일 크기 체크 | X | O |

---

## 10. 문서 버전 관리 / ETag 처리

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

---

## 11. KB 삭제 데이터 정리 순서

```
DELETE /api/kb/{kb_id}
    │
    ├─ 1. Postgres: knowledge_bases.status = "deleting"  (진행 중 표시)
    ├─ 2. Qdrant: Collection {kb_id} drop
    ├─ 3. S3: {bucket}/{kb_id}/ prefix 전체 삭제
    └─ 4. Postgres: knowledge_bases 행 삭제 (ON DELETE CASCADE → documents 자동 삭제)
```

---

## 12. LlamaIndex 활용 범위

### 파싱 — SimpleDirectoryReader

```python
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import PDFReader, MarkdownReader, DocxReader

reader = SimpleDirectoryReader(
    input_files=[local_path],
    file_extractor={
        ".pdf":  PDFReader(),
        ".md":   MarkdownReader(),
        ".docx": DocxReader(),
    }
)
documents = reader.load_data()
```

### 청킹 — NodeParser

```python
from llama_index.core.node_parser import (
    SentenceSplitter,            # recursive 전략
    SemanticSplitterNodeParser,  # semantic 전략
)

parsers = {
    "recursive": SentenceSplitter(chunk_size=1024, chunk_overlap=128),
    "semantic":  SemanticSplitterNodeParser(buffer_size=1, breakpoint_percentile_threshold=80),
}
```

### 임베딩 — LlamaIndex Embedding

```python
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

embeddings = {
    "ollama": OllamaEmbedding(model_name="bge-m3", base_url="http://ollama:11434"),
    "openai": OpenAIEmbedding(model="text-embedding-3-small", api_key=...),
}
```

### 검색 — VectorStoreIndex + QdrantVectorStore

```python
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.qdrant import QdrantVectorStore
from pipeline.ops.sparse import compute_sparse_tf

vector_store = QdrantVectorStore(
    client=qdrant_client,
    collection_name=kb_id,
    enable_hybrid=True,
    sparse_doc_fn=compute_sparse_tf,   # 인덱싱 시 TF sparse 벡터 생성
    sparse_query_fn=compute_sparse_tf, # 쿼리 시 TF sparse 벡터 생성
    dense_vector_name="dense",
    sparse_vector_name="sparse",
)
index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)
retriever = index.as_retriever(
    similarity_top_k=settings.retrieval.top_k,
    vector_store_query_mode="hybrid",
    alpha=settings.retrieval.alpha,
)
```

### Sparse 벡터 — 자체 TF 인코더 (pipeline/ops/sparse.py)

FastEmbed BM25를 직접 사용하지 않고, 순수 Python으로 구현한 TF 인코더(`compute_sparse_tf`)를 사용한다.
클라이언트는 TF만 계산하고, IDF는 Qdrant 서버가 코퍼스 기반으로 자동 관리한다(`Modifier.IDF`).
`sparse_doc_fn` / `sparse_query_fn`으로 LlamaIndex에 주입하여 인덱싱·검색 양쪽에서 동일하게 동작한다.

---

## 13. Dagster 정의 구조

### definitions.py

```python
# src/defs/definitions.py
from dagster import Definitions
from defs.jobs.ingest_job import ingest_job
from defs.jobs.delete_job import delete_job
from defs.sensors.event_queue_sensor import event_queue_sensor
from defs.resources.resources import build_resources_from_settings

defs = Definitions(
    jobs=[ingest_job, delete_job],
    sensors=[event_queue_sensor],
    resources=build_resources_from_settings(),  # S3PickleIOManager
)
```

### ingest_ops.py (핵심 Op 구조)

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

@op
def parse_op(context, valid_config: dict): ...

@op
def chunk_op(context, documents): ...

@op
def embed_op(context, nodes): ...

@op
def upsert_op(context, valid_config: dict, embedded_nodes): ...

@op
def meta_op(context, valid_config: dict, upsert_result): ...
```

### event_queue_sensor.py (핵심 구조)

```python
@sensor(jobs=[ingest_job, delete_job], minimum_interval_seconds=poll_interval_sec)
def event_queue_sensor(context: SensorEvaluationContext):
    # 1. delay 큐에서 준비된 항목을 main 큐로 복원
    _drain_delay_queue(r, UPLOAD_DELAY_KEY, UPLOAD_QUEUE_KEY)
    _drain_delay_queue(r, DELETE_DELAY_KEY, DELETE_QUEUE_KEY)

    count = 0
    # 2. PUT 큐 처리 → ingest_job
    while count < max_per_poll:
        raw = r.rpop(UPLOAD_QUEUE_KEY)
        if raw is None:
            break
        # 활성 run이 있으면 delay, zombie면 recover 후 dispatch
        if doc and _is_blocked_by_active_run(context, r, doc, UPLOAD_DELAY_KEY, ...):
            continue
        set_processing(kb_id, doc_source, etag=etag)
        yield RunRequest(run_key=str(uuid4()), job_name="ingest_job", ...)
        count += 1

    # 3. DELETE 큐 처리 → delete_job
    while count < max_per_poll:
        raw = r.rpop(DELETE_QUEUE_KEY)
        if raw is None:
            break
        if doc and _is_blocked_by_active_run(context, r, doc, DELETE_DELAY_KEY, ...):
            continue
        set_deleting(kb_id, doc_source)
        yield RunRequest(run_key=str(uuid4()), job_name="delete_job", ...)
        count += 1
```

### Dagster 설정 (docker/dagster.yaml)

```yaml
run_coordinator:
  module: dagster.core.run_coordinator
  class: QueuedRunCoordinator
  config:
    max_concurrent_runs: 8          # 동시 처리 문서 수
```

---

## 14. 로컬 실행 구조

### 실행 방법

```bash
# 단일 파일 S3 업로드 후 ingest 큐 enqueue
PYTHONPATH=src python -m main ingest \
  --kb-id kb-01 \
  --file ./data/ATD00002_2605.pdf

# KB 생성 (Postgres + Qdrant)
PYTHONPATH=src python -m main kb create --kb-id kb-01 --description "CNAP 플랫폼 문서"

# 검색 테스트
PYTHONPATH=src python -m main search \
  --kb-ids kb-01 \
  --query "Keycloak 설정 방법"

# FastAPI 서버 실행
PYTHONPATH=src python -m main serve

# Dagster UI 로컬 실행
dagster dev -f src/defs/definitions.py
# → http://localhost:3000
```

### main.py 구조

```python
# src/main.py (Typer CLI)
app = typer.Typer()
kb_app = typer.Typer()
app.add_typer(kb_app, name="kb")

@app.command()
def ingest(kb_id: str, file: Path, force: bool = False):
    # S3 업로드 후 Redis 큐 enqueue (Dagster sensor가 소비)
    etag = upload_object(kb_id=kb_id, doc_source=file.name, data=content)
    enqueue_upload_event(kb_id=kb_id, doc_source=file.name, etag=etag, ...)

@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    uvicorn.run("api.app:create_app", host=host, port=port, factory=True)

@app.command()
def search(kb_ids: list[str], query: str, top_k: int = 10):
    results = asyncio.run(hybrid_search(query=query, kb_ids=kb_ids, top_k=top_k))
    ...
```

### pipeline/runner.py — 직접 파이프라인 실행 (Dagster 없이)

```python
def run_ingest_pipeline(
    kb_id: str, doc_source: str, etag: str = "",
    file_size: int = 0, force: bool = False, run_id: str = "direct",
) -> int:
    should_process = validate(kb_id, doc_source, etag, file_size, force=force)
    if not should_process:
        return 0                          # ETag 동일 → skip

    documents = parse(kb_id, doc_source) # S3에서 다운로드 후 파싱
    nodes     = chunk(documents)
    embedded  = embed(nodes)
    result    = upsert(kb_id, doc_source, embedded)
    update_meta(kb_id, doc_source, result, etag=etag, run_id=run_id)
    return result.chunk_count
```
