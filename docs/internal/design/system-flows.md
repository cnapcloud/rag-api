# 시스템 처리 흐름

인제스트·삭제·검색·이벤트·커넥터 각 기능의 런타임 처리 흐름.
컴포넌트 구조와 설계 원칙은 [architecture.md](../dev/architecture.md) 참조.
내부 상태·스키마·키 구조는 [internals.md](internals.md) 참조.

---

## 1. Dagster 태스크 흐름

### ingest_job (문서 1개 단위)

```
event_queue_sensor (Redis rag:upload:queue)
    │  PUT 이벤트 1건 → RunRequest 1개 (max_per_poll 한도 내 배치 소비)
    ↓
validate_op
    │  ETag 중복 → 스킵 (status 복원 후 종료)
    │  파일 크기 초과 → 실패 처리
    ↓
parse_op          (LlamaIndex SimpleDirectoryReader)
    │  PDF/MD/Word → Document 객체
    ↓
chunk_op          (LlamaIndex SentenceSplitter / SemanticSplitter)
    │  Document → Node 리스트 (청크 N개)
    ↓
embed_op          (LlamaIndex OllamaEmbedding / OpenAIEmbedding)
    │  Node 리스트 → asyncio.gather로 배치 병렬 임베딩
    │  Dense(bge-m3) + Sparse(자체 TF 인코더) 동시 생성
    ↓
upsert_op         (Qdrant Python Client)
    │  기존 청크 삭제 (doc_key 필터) → 신규 청크 배치 삽입
    ↓
meta_op           (Postgres)
    │  status → indexed, etag, chunk_count, updated_at 갱신
```

### delete_job (문서 1개 단위)

```
event_queue_sensor (Redis rag:delete:queue)
    │  DELETE 이벤트 1건 → RunRequest 1개
    ↓
delete_chunks_op  (Qdrant)
    │  doc_key 필터로 청크 전체 삭제
    ↓
delete_meta_op    (Postgres)
    │  documents 테이블에서 (kb_id, doc_source) 행 삭제
```

---

## 2. 검색(Search) 흐름

```
POST /api/search  (또는 MCP search 툴)
    │  {query, kb_ids, top_k, mode, min_score}
    ↓
retriever.search()   — kb_ids별 병렬 Qdrant 쿼리
    │  hybrid: dense(코사인) + sparse(BM25) 동시 검색
    │  similarity: dense 전용
    │  → SearchResult[] per KB
    ↓
merger.rrf_merge()   — multi-KB RRF 병합
    │  각 KB 결과를 순위 기반으로 단일 리스트로 합산
    ↓
reranker.rerank_async()   — Jina Reranker API
    │  fallback: Jina 실패 시 RRF 점수 그대로 사용
    ↓
SearchResponse  {results: [{text, score, rerank_score, kb_id, doc_key, page_num}]}
```

검색은 읽기 전용이며 Dagster와 무관하다. 실패한 KB는 로그만 남기고 빈 결과로 처리한다(단일 KB 오류가 전체 응답을 막지 않음).

---

## 3. 이벤트 처리 경로

```
[경로 A — 업로드 (주 경로)]
POST /api/kb/{id}/docs/upload (또는 /batch)
    → S3(MinIO) 저장
    → MinIO Webhook → POST /internal/s3-event
    → Redis 큐(rag:upload:queue) push

[경로 B — 재인덱스 / 수동 트리거]
POST /api/kb/{id}/docs/reindex (또는 /recover)
    → enqueue_upload_event() 직접 호출
    → Redis 큐(rag:upload:queue) push

[공통 — Dagster 모드]
rag:upload:queue (list)
    → event_queue_sensor (poll_interval_sec 주기)
        1. _drain_delay_queue(): rag:upload:delay 중 score 만료된 항목 → rag:upload:queue 복원
        2. rpop → doc status 확인
            - run_id가 Dagster에서 실행 중 → rag:upload:delay에 재투입 (score = now + retry_interval_sec)
            - 실행 중 아님(zombie) → set_failed() 후 RunRequest 생성
            - 정상 → RunRequest 생성 → Dagster Run 실행

[공통 — QueueWorker 모드]
rag:upload:queue (list)
    → QueueWorker (poll_interval_sec 주기)
        - rpop → doc status 확인
            - status = running 또는 deleting → retry_interval_sec 후 rag:upload:queue 재투입
              (run_id 조회 불가 — status 기반으로만 판단, zombie 복구 없음)
            - 정상 → run_ingest_pipeline() 직접 실행
```

업로드 엔드포인트는 S3 저장만 수행하고 Redis enqueue는 MinIO Webhook이 담당한다.
재인덱스·복구 엔드포인트는 `enqueue_upload_event()`를 직접 호출해 큐에 push한다.

큐 소비 주체는 배포 환경에 따라 다르다.

| 환경 | 소비 주체 | 설정 | delay 큐 | zombie 복구 |
|------|-----------|------|-----------|------------|
| Dagster 있음 | `event_queue_sensor` | `queue_worker.enabled: false` | `rag:upload:delay` (sorted set) | O (run_id로 Dagster 확인) |
| Dagster 없음 | `QueueWorker` (FastAPI asyncio) | `queue_worker.enabled: true` | main queue 재투입 (list) | X (status 기반 판단만) |

`QueueWorker`는 Dagster run_id를 조회할 수 없으므로 status=running인 doc을 만나면 zombie 여부를 판단하지 않고 단순 재시도한다. zombie가 발생한 경우 수동으로 status를 reset해야 한다.

### 이벤트 라이프사이클 (Dagster 모드)

```
enqueue_upload_event()
    → doc status: pending
    → rag:upload:queue push

event_queue_sensor (5초 주기)
    → _drain_delay_queue: rag:upload:delay → rag:upload:queue (score 만료분)
    → rpop from rag:upload:queue
        [A] run_id 있고 Dagster에서 실행 중
            → rag:upload:delay push (score = now + 10초)  ← 10초 후 재시도
        [B] run_id 있으나 Dagster에서 종료/미존재 (zombie)
            → set_failed()  → doc status: failed
            → RunRequest 생성 → Dagster Run 실행
            → doc status: running
        [C] 정상 (blocking run 없음)
            → set_processing() → doc status: running
            → RunRequest 생성 → Dagster Run 실행

Dagster Run 완료
    → meta_op: doc status: indexed (성공) / failed (실패)
```

delay queue(`rag:upload:delay`)는 Redis sorted set이며 score = 재시도 예정 시각(unix timestamp)이다.
동일 이벤트가 여러 번 들어와도 각 이벤트는 고유한 `_retry_id`를 가지므로 dedup 없이 독립적으로 쌓인다.

---

## 4. 커넥터(Connector) 흐름

외부 소스(GitHub, Confluence, Web)에서 문서를 주기적으로 가져와 인제스트 파이프라인에 투입하는 컴포넌트.

### 기본 구조

```
src/connectors/
  github.py       # GitHubConnector — 레포 파일 fetch
  confluence.py   # ConfluenceConnector — 페이지/첨부파일 fetch
  web.py          # WebConnector — 시드 URL 크롤링
  factory.py      # source_type → Connector 클래스 매핑 (미사용, dispatch는 routers에서)
```

각 커넥터는 `sync(kb_id, connector_id)` 메서드 하나만 외부에 노출한다. 내부에서 파일 목록 조회 → 개별 파일 다운로드 → S3 스테이징 → 인제스트 큐 투입을 순차 처리한다.

커넥터 설정(`config`)은 Postgres `connectors` 테이블에 JSON으로 저장되며, `auth_token_secret` 등 민감 필드는 Fernet(AES-128)으로 암호화된다. 복호화는 `_dispatch_sync` 호출 시점에만 수행되고 API 응답에는 `"***"`으로 마스킹된다.

### 상태 처리 흐름

```
POST /api/connectors/{id}/sync
  → set sync_status = "running"
  → BackgroundTask: _run_sync()
      → _dispatch_sync()
          → decrypt_config()
          → Connector(config).sync(kb_id, connector_id)
              파일별:
                get_doc_by_source_uri()
                  [신규] create_doc(status="fetching")
                  [기존] update_doc_fields(status="fetching")
                download_file() → upload_to_s3() → enqueue_upload_event()
                  → doc status: pending → running → indexed / failed
      → set sync_status = "idle", last_synced_at = now
  오류 시:
      → set connector status = "error"
      → set sync_status = "idle"
```

### 커넥터 / 문서 상태 구분

| 구분 | 필드 | 값 |
|------|------|----|
| 커넥터 실행 상태 | `sync_status` | `idle` / `running` |
| 커넥터 운영 상태 | `status` | `active` / `paused` / `error` / `deleting` |
| 문서 인제스트 상태 | `status` | `fetching` → `pending` → `running` → `indexed` / `failed` |

`sync_status`는 현재 sync 작업 진행 여부만 나타낸다. `schedule_enabled`가 `false`이면 Dagster 스케줄이 tick해도 `SkipReason`을 반환하고 실제 run을 생성하지 않는다.

운영 액션(상태 값이 아님):

| 액션 | 수단 | 설명 |
|------|------|------|
| Pause | `PATCH status: "paused"` | 수동/자동 sync 전면 차단 |
| Resume | `PATCH status: "active"` | pause 해제 |
| Reset | `POST /sync/reset` | `sync_status`가 stuck된 경우 `idle`로 강제 초기화. 실행 중 작업을 중단하지는 않음 |

### 스케줄 등록

`sync_schedule`(cron)이 설정된 커넥터는 **Dagster 컨테이너 시작 시** `load_connector_schedules()`가 DB를 조회해 `ScheduleDefinition`으로 등록한다. `dagster api grpc` 방식은 런타임 reload를 지원하지 않으므로, `sync_schedule` 변경 시 Dagster 컨테이너 재시작이 필요하다. `schedule_enabled` 토글은 재시작 없이 즉시 반영된다(execution_fn에서 DB 재조회).

---

## 5. MCP 서버

FastMCP 기반 LLM 툴 인터페이스. `search`, `list_knowledge_bases`, `get_document_status` 3개 툴을 노출한다.
FastAPI 프로세스에 embedded(`/mcp` 엔드포인트)되거나 `python -m main serve-mcp`로 독립 실행된다.

자세한 설계는 [mcp.md](mcp.md) 참조.
