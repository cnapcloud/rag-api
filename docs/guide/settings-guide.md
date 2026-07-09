# Settings Guide

`settings.yaml`의 모든 설정 항목을 섹션별로 설명하고, 운영 시 고려해야 할 사항을 정리한다.

설정 파일 위치: `settings.yaml` (프로젝트 루트), `docker/settings.yaml` (컨테이너 배포용)

모든 항목은 환경변수로 오버라이드 가능하다. Pydantic Settings 규칙을 따르며, 중첩 키는 `__`로 구분한다. 예: `QDRANT__HOST=192.168.0.184`.

---

## 1. dagster

Dagster 웹서버 연결 설정. 큐 워커 모드(`queue_worker.enabled: true`)에서는 사용되지 않는다.

```yaml
dagster:
  endpoint: "http://localhost:3000"
```

| 키 | 설명 |
|----|------|
| `endpoint` | Dagster 웹서버 URL. workspace reload(`reloadWorkspace`)와 run 강제 종료(`terminateRun`) GraphQL 호출에 사용됨. `queue_worker.enabled: true`이면 no-op |

**운영 고려사항**

- 컨테이너 환경에서는 `http://dagster-webserver:3000` 형식의 내부 네트워크 주소를 사용한다.
- 실제 job 실행은 gRPC(`dagster-rag-api:4000`)를 통해 이루어지며 이 설정과 무관하다.
- `queue_worker.enabled: false` 모드에서 이 주소에 접근할 수 없으면 커넥터 스케줄 reload는 warning 로그만 남기고 무시되지만, run terminate 실패는 `RuntimeError`로 상위에 전파된다.

---

## 2. s3

MinIO(S3 호환) 오브젝트 스토리지 연결 설정. 업로드 파일과 커넥터가 수집한 원본 문서를 저장한다.

```yaml
s3:
  endpoint: "http://192.168.0.185:9000"
  access_key: "admin"
  secret_key: "password"
  rag_bucket: "rag-api"
  dagster_bucket: "dagster"
  region: "us-east-1"
  insecure: true
```

| 키 | 설명 |
|----|------|
| `endpoint` | MinIO 서버 주소 (포트 포함) |
| `access_key` | 접근 키 (MinIO root user) |
| `secret_key` | 시크릿 키 (MinIO root password) |
| `rag_bucket` | 문서 저장 버킷 이름 |
| `dagster_bucket` | Dagster 아티팩트 저장 버킷 이름 |
| `region` | 리전 (S3 호환성용, 실질 영향 없음) |
| `insecure` | `true`: HTTP 사용. `false`: HTTPS + 인증서 검증 |

**운영 고려사항**

- `secret_key`는 평문으로 파일에 저장하지 않도록 한다. 프로덕션에서는 환경변수(`S3__SECRET_KEY`)로 주입한다.
- `insecure: false` 전환 시 MinIO가 유효한 TLS 인증서를 사용해야 한다. Let's Encrypt 또는 내부 CA 인증서를 MinIO에 적용한 후 변경한다.
- `rag_bucket`과 `dagster_bucket`은 사전에 생성되어 있어야 한다. `minio-init` 컨테이너가 이를 담당한다.

---

## 3. postgres

KB, 문서, 커넥터 메타데이터와 dedup 밴드(SimHash/MinHash)를 저장하는 Postgres 연결 설정.

```yaml
postgres:
  host: "postgresql"
  port: 5432
  dbname: "rag-api"
  user: "rag-api"
  password: "password"
  pool_size: 5
  connect_timeout: 30
```

| 키 | 기본값 | 설명 |
|----|--------|------|
| `host` | — | Postgres 호스트 |
| `port` | `5432` | Postgres 포트 |
| `dbname` | — | 데이터베이스 이름 |
| `user` | — | 접속 유저 |
| `password` | — | 비밀번호 |
| `pool_size` | `5` | asyncpg 연결 풀 크기 |
| `connect_timeout` | `30` | 연결 타임아웃(초) |

**운영 고려사항**

- `pool_size`는 `queue_worker.max_workers`와 연계해 설정한다. 동시 처리 워커 수보다 약간 크게 설정하는 것이 일반적이다. 예: `max_workers: 5` → `pool_size: 7`.
- Postgres `max_connections`가 낮으면 커넥션 풀 생성에 실패한다. 기본값(`100`) 기준으로 rag-api, Dagster 컨테이너가 각자 `pool_size`만큼 연결을 가져간다는 점을 고려한다.
- `connect_timeout`은 네트워크 장애 감지 속도에 영향을 준다. 너무 낮으면 일시적 지연에도 연결 실패로 처리된다.
- 비밀번호는 `POSTGRES__PASSWORD` 환경변수로 주입하는 것을 권장한다.

---

## 4. qdrant

벡터 DB 연결 설정. 문서 청크의 dense/sparse 임베딩을 저장하고 검색한다.

```yaml
qdrant:
  host: "192.168.0.184"
  port: 6333
  insecure: true
```

| 키 | 설명 |
|----|------|
| `host` | Qdrant 서버 호스트 |
| `port` | gRPC 포트 (`6333`: REST, `6334`: gRPC — 코드는 REST 사용) |
| `insecure` | `true`: HTTP 사용. `false`: HTTPS |

**운영 고려사항**

- Qdrant는 재시작 시 메모리 맵 파일로부터 컬렉션을 복구한다. 볼륨(`qdrant_storage`)이 유지되는 한 데이터가 보존된다.
- 컬렉션은 `embedding.vector_size`와 맞아야 한다. 모델을 변경하면서 `vector_size`도 바꾸면 기존 컬렉션과 충돌한다 — 컬렉션을 삭제하고 전체 재인덱싱이 필요하다.
- 대용량 컬렉션(수백만 벡터)에서는 Qdrant 메모리 사용량이 급격히 늘어날 수 있다. Qdrant 공식 권장: 벡터 차원 × 4바이트 × 벡터 수를 RAM으로 확보한다. bge-m3(1024차원), 50만 벡터 기준 약 2GB.

---

## 5. redis

인제스트·삭제 이벤트 큐 전용 Redis 연결 설정. API가 enqueue한 이벤트를 `event_queue_sensor`(Dagster 모드) 또는 `QueueWorker`(내장 워커 모드)가 소비해 파이프라인을 실행한다.

```yaml
redis:
  host: "192.168.0.183"
  port: 6379
  password: "redis"
  db: 0
```

| 키 | 설명 |
|----|------|
| `host` | Redis 호스트 |
| `port` | Redis 포트 |
| `password` | Redis AUTH 비밀번호. 없으면 빈 문자열 |
| `db` | Redis DB 인덱스 (0~15) |

**운영 고려사항**

- 기본 설정은 RDB 스냅샷 모드다. Redis 비정상 종료 시 마지막 스냅샷 이후에 enqueue된 이벤트가 유실될 수 있다. 무중단 운영이 필요하면 AOF를 활성화한다 — 자세한 절차는 [operations-guide.md](operations-guide.md) 5-3 참고.
- Redis DB 인덱스를 변경하면 기존 큐 데이터가 보이지 않아 미처리 이벤트가 유실된다. 운영 중 변경은 금지한다.
- `password`는 `REDIS__PASSWORD` 환경변수로 주입하는 것을 권장한다.

---

## 6. ingestion

파일 업로드 및 커넥터 수집 단계의 제한 설정.

```yaml
ingestion:
  max_file_size_mb: 10
  min_content_chars: 200
  html_favor_precision: true
```

| 키 | 기본값 | 설명 |
|----|--------|------|
| `max_file_size_mb` | `10` | 파일 업로드 최대 크기(MB). 초과 시 422 반환 |
| `min_content_chars` | `200` | 웹 커넥터 전용. trafilatura 본문 추출 결과가 이 값 미만인 페이지는 저장 제외 |
| `html_favor_precision` | `true` | `pipeline/ops/parse.py`의 `HTMLCleanReader`(`.html`/`.htm` 파싱)가 trafilatura로 본문을 추출할 때 정밀도(precision) 우선 모드 사용 여부. `true`면 본문인지 애매한 블록(사이드바 경계 등)을 제외해 dedup stage 1(SimHash) 안정성을 높이지만 본문 일부가 드물게 손실될 수 있다. `false`면 재현율(recall) 우선으로 전환되어 애매한 블록도 포함한다 |

**운영 고려사항**

- `max_file_size_mb`를 크게 올리면 파싱·임베딩 시간이 선형 이상으로 늘어날 수 있다. 대용량 PDF(100MB+)는 LlamaIndex 파서가 메모리를 수백 MB 사용한다. 실제 필요 크기를 기준으로 보수적으로 설정한다.
- `min_content_chars`는 크롤 대상 사이트의 특성에 따라 조정한다. 짧은 페이지(FAQ, 카드형 UI)가 많은 사이트에서는 너무 높게 설정하면 유효한 문서가 걸러질 수 있다. 수집 결과를 확인한 후 조정한다.
- `html_favor_precision`은 기본값(`true`)을 유지하는 것을 권장한다. HTML 문서에서 본문이 자주 잘려나간다는 신호(청크 수가 비정상적으로 적음, 특정 사이트의 문서가 계속 dedup 오탐됨 등)가 관찰되면 `false`로 전환해 재검증한다 (`docs/internal/design/html-extraction.md` 3.2, 6절 오픈 이슈 참고).

---

## 7. dedup

중복 문서 탐지 설정. 파이프라인에서 validate 단계 직후, parse 전에 실행된다. Stage별(SimHash/MinHash/
chunk_compare) 하위 섹션으로 중첩되어 있다 — 어떤 값이 어느 단계 것인지 이름만으로 구분하기 위함
(2026-07-09, `docs/internal/design/dedup.md` 3.3 참고).

중복 비교 대상은 **정상 색인된(`indexed`) 문서로 한정된다.** 이미 중복으로 처리되어 검색에서
제외된 문서(`outdated`)나 처리 중/실패/삭제된 문서는 비교 대상에 포함되지 않는다.

```yaml
dedup:
  enabled: true

  simhash:                                 # Stage1 - SimHash 근접 중복 탐지
    ngram: 3
    num_bands: 4
    simhash_bits: 64
    hamming_identical_threshold: 2
    hamming_similar_threshold: 5

  minhash:                                 # Stage2 - MinHash/제목 유사도 (Stage1 후보 없을 때만 실행)
    jaccard_threshold: 0.65
    title_fuzzy_threshold: 0.85
    title_only_min_jaccard_floor: 0.25
    user_words_path: "data/kiwi_user_words.tsv"

  chunk_compare:                           # Stage3 - 임베딩 기반 청크 단위 정밀 비교
    chunk_match_threshold: 0.50
    body_identical_threshold: 0.95
    body_similar_threshold: 0.75
    compare_all_candidates: false
```

### 7-1. 작동 흐름

```
Stage 1 (SimHash)
  → hamming distance <= simhash.hamming_identical_threshold  → identical 판정 → 인덱싱 건너뜀
  → hamming distance <= simhash.hamming_similar_threshold    → Stage 3(chunk_compare)로 라우팅
  → 그 외                                                    → Stage 2 진입

Stage 2 (MinHash + pg_trgm, Stage1 후보 없을 때만)
  → MinHash Jaccard >= minhash.jaccard_threshold             → Stage 3(chunk_compare)로 라우팅
  → Title pg_trgm similarity >= minhash.title_fuzzy_threshold
    AND MinHash Jaccard >= minhash.title_only_min_jaccard_floor → Stage 3(chunk_compare)로 라우팅
  → 그 외                                                    → unique 판정 → 정상 인덱싱

Stage 3 (chunk_compare, Stage1/2가 "similar" 후보를 넘겼을 때만)
  → 임베딩 코사인 유사도 집계 점수(청크 수 비율로 스케일링됨) >= chunk_compare.body_identical_threshold → identical 판정
  → 집계 점수 >= chunk_compare.body_similar_threshold                                                → similar 판정 (기존 문서 outdated, 신규 색인)
  → 그 외                                                                                            → unique 판정 → 정상 인덱싱
```

| 키 | 기본값 | 설명 |
|----|--------|------|
| `enabled` | `true` | `false`로 설정하면 dedup 단계 전체 건너뜀 |
| **simhash** (Stage1) | | |
| `simhash.ngram` | `3` | SimHash 생성에 사용할 문자 n-gram 크기 |
| `simhash.num_bands` | `4` | SimHash 밴드 수. 클수록 후보 정밀도 증가, 처리량 감소 |
| `simhash.simhash_bits` | `64` | SimHash 해시 비트 수 (64 고정 권장) |
| `simhash.hamming_identical_threshold` | `2` | 이 값 이하이면 identical로 즉시 판정 |
| `simhash.hamming_similar_threshold` | `5` | 이 값 이하이면 Stage 3(chunk_compare)로 넘김 |
| **minhash** (Stage2) | | |
| `minhash.jaccard_threshold` | `0.65` | MinHash Jaccard 유사도 임계값 |
| `minhash.title_fuzzy_threshold` | `0.85` | 제목 유사도 임계값 (pg_trgm similarity) |
| `minhash.title_only_min_jaccard_floor` | `0.25` | 제목만으로 후보 판정할 때 본문 유사도 최솟값 |
| `minhash.user_words_path` | `""` | Kiwi 형태소 분석기 사용자 사전 경로 (빈 값 = 사용 안 함) |
| **chunk_compare** (Stage3) | | |
| `chunk_compare.chunk_match_threshold` | `0.50` | 청크쌍 필터 임계값 (Top-1 매칭 최소 점수) |
| `chunk_compare.body_identical_threshold` | `0.95` | 집계 점수가 이 값 이상이면 body=identical |
| `chunk_compare.body_similar_threshold` | `0.75` | 집계 점수가 이 값 이상(identical 미만)이면 body=similar |
| `chunk_compare.compare_all_candidates` | `false` | `false`=best match 1건만 정밀 비교, `true`=후보 전체 순회 |

**운영 고려사항**

- `hamming_identical_threshold`와 `hamming_similar_threshold`는 역전되어서는 안 된다 (`identical <= similar`).
- `jaccard_threshold`를 낮추면 더 느슨하게 중복을 판정한다. 도메인 특화 문서(법령, 기술 문서 등)에서는 유사 표현이 많아 0.5 이하로 낮추면 오탐이 늘어날 수 있다.
- `user_words_path`는 Kiwi 형태소 분석기가 인식하지 못하는 고유명사·약어를 등록하는 용도다. 정확도를 높이려면 도메인 사전을 작성해 경로를 설정한다.
- `enabled: false`는 dedup 전체를 끄므로 성능 이슈 디버깅 외에는 운영 중 사용하지 않는다.

---

## 8. queue_worker

인제스트 이벤트를 처리하는 워커 방식 선택.

```yaml
queue_worker:
  enabled: true
  max_workers: 5
```

| 키 | 기본값 | 설명 |
|----|--------|------|
| `enabled` | `true` | `true`: rag-api 내장 AsyncIO 워커 사용. `false`: Dagster 센서 사용 |
| `max_workers` | `5` | 내장 워커 모드에서 동시 처리 가능한 최대 문서 수 |

**운영 고려사항**

| 모드 | 장점 | 단점 |
|------|------|------|
| `enabled: true` (내장 워커) | 별도 인프라 불필요, 배포 단순 | 태스크 강제 종료 불가, Dagster UI에서 실행 이력 미확인, **커넥터 sync 자동 스케줄 미지원** |
| `enabled: false` (Dagster) | 실행 이력·실패 추적 가능, run 강제 종료 가능, 커넥터 sync 자동 스케줄 지원 | Dagster 컨테이너 필요 |

- `max_workers`는 `postgres.pool_size`, 임베딩 서버(Ollama) 처리 용량을 고려해 설정한다. 내장 워커 기준 워커 1개가 embed 단계에서 Ollama에 집중적으로 요청을 보낸다. Ollama가 단일 모델 단일 GPU 구성이라면 `max_workers: 3` 정도가 실질 한계인 경우가 많다.
- 내장 워커 모드에서 `status=running` 문서는 force-fail API로만 상태를 변경할 수 있으며 실제 AsyncIO 태스크는 종료되지 않는다. 태스크가 완료되면 상태를 덮어쓸 수 있으므로 주의한다.

---

## 9. queue_poll

Redis 큐 폴링 설정. Dagster 센서 모드에서는 Dagster가 독자적인 tick 간격을 사용하며 이 설정은 내장 워커 모드에만 적용된다.

```yaml
queue_poll:
  poll_interval_sec: 5
  max_per_poll: 5
  retry_interval_sec: 10
```

| 키 | 기본값 | 설명 |
|----|--------|------|
| `poll_interval_sec` | `5` | Redis 큐를 확인하는 주기(초) |
| `max_per_poll` | `5` | 한 번의 poll에서 꺼낼 최대 이벤트 수 |
| `retry_interval_sec` | `10` | 동일 문서가 이미 처리 중일 때 delay queue에서 재시도 대기 시간(초) |

**운영 고려사항**

- `max_per_poll`은 `queue_worker.max_workers`와 동일하거나 작게 설정한다. 크게 설정하면 워커보다 더 많은 이벤트를 꺼내서 일부가 즉시 delay queue로 밀린다.
- `poll_interval_sec`를 낮추면 응답성이 올라가지만 Redis 연결 빈도가 늘어난다. 5초는 대부분의 워크로드에서 적절하다.
- `retry_interval_sec`는 동시에 같은 문서가 업로드되었을 때 두 번째 요청이 얼마나 기다렸다가 재시도할지를 결정한다. 너무 낮으면 Redis delay sorted set의 조회 빈도가 높아진다.

---

## 10. chunking

문서를 검색 가능한 청크로 분할하는 방식 설정.

```yaml
chunking:
  strategy: "recursive"
  chunk_size: 1024
  chunk_overlap: 128
  min_chunk_chars: 30
  semantic_threshold: 0.8
  code_chunk_lines: 40
  code_chunk_lines_overlap: 5
```

| 키 | 기본값 | 설명 |
|----|--------|------|
| `strategy` | `"recursive"` | `recursive`: 구분자 기반 재귀 분할. `semantic`: 임베딩 유사도 기반 분할 |
| `chunk_size` | `1024` | 청크당 최대 토큰(문자) 수 |
| `chunk_overlap` | `128` | 인접 청크 간 겹치는 토큰(문자) 수 |
| `min_chunk_chars` | `30` | 분할 후 이 값보다 짧은 청크는 버림 |
| `semantic_threshold` | `0.8` | `semantic` 전략에서 청크를 합칠 유사도 임계값 |
| `code_chunk_lines` | `40` | GitHub 소스코드 파일에 적용하는 줄 수 기준 청크 크기 |
| `code_chunk_lines_overlap` | `5` | 소스코드 청크 간 겹치는 줄 수 |

**운영 고려사항**

- `chunk_size`는 임베딩 모델의 입력 길이 제한에 맞게 설정한다. bge-m3의 토큰 제한은 8192이며, 1024는 여유롭게 맞는 크기다. `text-embedding-3-small`은 8191 제한이므로 유사하다.
- `chunk_overlap`을 늘리면 청크 경계에서 의미가 끊어지는 문제를 줄일 수 있지만 청크 수가 늘어나 Qdrant 스토리지와 검색 비용이 증가한다. `chunk_size`의 10~15% 수준이 일반적이다.
- `semantic` 전략은 recursive 대비 임베딩 호출이 추가로 발생해 청킹 속도가 느려진다. 대량 문서 환경에서는 비용·속도 트레이드오프를 확인한 후 사용한다.
- `min_chunk_chars`는 목차, 헤더만 있는 청크가 인덱싱되는 것을 방지한다. 너무 높게 설정하면 유효한 짧은 내용이 버려질 수 있다.

---

## 11. embedding

임베딩 모델 설정. dense 벡터 생성에 사용하며, sparse는 클라이언트가 TF만 계산하고 IDF는 Qdrant 서버가 코퍼스 기반으로 자동 관리한다.

```yaml
embedding:
  provider: "ollama"
  model: "bge-m3"
  vector_size: 1024
  ollama_url: "http://localhost:11434"
  openai_api_key: ""
  openai_model: "text-embedding-3-small"
```

| 키 | 기본값 | 설명 |
|----|--------|------|
| `provider` | `"ollama"` | `ollama`: 로컬 Ollama 서버. `openai`: OpenAI API |
| `model` | `"bge-m3"` | Ollama 모델 이름 |
| `vector_size` | `1024` | Dense 벡터 차원수. 모델과 일치해야 함 |
| `ollama_url` | `"http://localhost:11434"` | Ollama 서버 주소 |
| `openai_api_key` | `""` | OpenAI provider 사용 시 필수 |
| `openai_model` | `"text-embedding-3-small"` | OpenAI 임베딩 모델 이름 |

**모델별 vector_size**

| 모델 | provider | vector_size |
|------|----------|-------------|
| `bge-m3` | ollama | `1024` |
| `nomic-embed-text` | ollama | `768` |
| `text-embedding-3-small` | openai | `1536` |
| `text-embedding-ada-002` | openai | `1536` |

**운영 고려사항**

- `vector_size`를 잘못 설정하면 Qdrant 컬렉션 생성 시 `ConfigError`로 기동이 실패한다. 모델 변경 시 반드시 함께 수정한다.
- **모델 변경은 전체 재인덱싱을 수반한다.** 기존 Qdrant 컬렉션은 이전 차원으로 생성되어 있으므로 삭제 후 재생성해야 한다. KB별 `DELETE /api/kb/{id}` 후 재생성 → `POST /api/kb/{id}/reindex?force=true` 순서로 진행한다.
- Ollama 모델은 첫 요청 시 모델 파일을 로드한다. 이 과정이 수십 초 걸릴 수 있다. 서비스 기동 직후 `/ready` 엔드포인트 확인 시 `ollama: false`가 나오면 모델 로딩 중인 경우다.
- `openai_api_key`는 `EMBEDDING__OPENAI_API_KEY` 환경변수로 주입한다. 파일에 직접 기록하지 않는다.

---

## 12. retrieval

검색 방식과 파라미터 설정. 요청 시 `options` 필드로 오버라이드 가능하다.

```yaml
retrieval:
  mode: "hybrid"
  top_k: 5
  hybrid:
    alpha: 0.5
    rrf_k: 60
  similarity:
    min_score: 0.0
  rerank:
    enabled: false
    provider: "jina"
    api_key: ""
    model: "jina-reranker-v2-base-multilingual"
    top_n: 3
    timeout_sec: 5
    fallback_on_error: true
```

### 12-1. 기본 설정

| 키 | 기본값 | 설명 |
|----|--------|------|
| `mode` | `"hybrid"` | `hybrid`: dense + sparse RRF. `similarity`: dense 코사인 유사도만 사용 |
| `top_k` | `5` | 반환할 최대 청크 수 |

### 12-2. hybrid 설정

| 키 | 기본값 | 설명 |
|----|--------|------|
| `alpha` | `0.5` | Dense와 Sparse의 가중치 비율. `1.0` = Dense 100%, `0.0` = Sparse(키워드) 100% |
| `rrf_k` | `60` | RRF 점수 공식 `1/(k+rank)`의 k값. 클수록 상위 순위와 하위 순위의 점수 차이가 줄어듦 |

**운영 고려사항 (hybrid)**

- `alpha: 0.5`는 중립 출발점이다. 키워드 일치가 중요한 도메인(법령, 기술 명세)에서는 `0.3` 이하로, 의미 검색이 중요한 도메인(QA, 요약)에서는 `0.7` 이상으로 조정을 검토한다.
- `rrf_k: 60`은 업계 표준값이다. 변경 효과가 미미하므로 특별한 이유 없이 바꾸지 않는다.
- hybrid 모드에서 `min_score`는 적용되지 않는다. 결과 수 제어는 `top_k`만으로 한다.

### 12-3. similarity 설정

| 키 | 기본값 | 설명 |
|----|--------|------|
| `min_score` | `0.0` | 이 값 미만의 코사인 유사도 결과를 제외. `0.0`은 필터 없음 |

**운영 고려사항 (similarity)**

- `min_score: 0.0`은 관련성이 낮은 결과도 모두 반환한다. 품질 확인 후 `0.4`~`0.6` 수준으로 올리는 것을 권장한다.
- bge-m3 기준 코사인 유사도 0.5 이하는 대체로 주제가 다른 문서다. 도메인에 따라 기준이 달라지므로 실제 검색 결과를 모니터링하며 조정한다.

### 12-4. rerank 설정

| 키 | 기본값 | 설명 |
|----|--------|------|
| `enabled` | `false` | 리랭킹 활성화 여부 |
| `provider` | `"jina"` | 현재 `jina`만 지원 |
| `api_key` | `""` | Jina API 키 |
| `model` | `"jina-reranker-v2-base-multilingual"` | Jina 리랭킹 모델 |
| `top_n` | `3` | 리랭킹 후 반환할 최종 결과 수 |
| `timeout_sec` | `5` | Jina API 응답 타임아웃(초) |
| `fallback_on_error` | `true` | Jina 호출 실패 시 RRF 점수 순으로 대체 반환 |

**운영 고려사항 (rerank)**

- `enabled: true`로 변경하면 검색 응답 시간이 Jina API 왕복 시간(통상 200~500ms)만큼 늘어난다. 지연 허용치를 확인한 후 활성화한다.
- `fallback_on_error: true`를 유지하면 Jina API가 일시 다운돼도 검색 자체는 중단되지 않는다. 다만 리랭킹 품질 없이 RRF 점수로 반환된다.
- `api_key`는 `RETRIEVAL__RERANK__API_KEY` 환경변수로 주입한다.
- `top_n`은 `top_k`보다 작아야 의미가 있다. 리랭킹은 `top_k` 결과를 재순위 매긴 뒤 상위 `top_n`개만 반환한다.

---

## 13. knowledge_bases

시스템에 사전 등록할 KB 목록. 서버 기동 시 DB에 없는 KB를 자동 생성한다.

```yaml
knowledge_bases:
  - id: "kb-01"
    name: "지식베이스 01"
    description: "첫 번째 지식베이스입니다."
    tags: ["general"]
  - id: "kb-02"
    name: "지식베이스 02"
    description: "두 번째 지식베이스입니다."
```

| 키 | 필수 | 설명 |
|----|------|------|
| `id` | 필수 | KB 고유 식별자. 생성 후 변경 불가 |
| `name` | 선택 | 표시 이름 |
| `description` | 선택 | 설명 |
| `tags` | 선택 | 태그 목록 |

**운영 고려사항**

- 이 목록은 초기 생성용이다. 이미 존재하는 KB는 기동 시 변경되지 않는다. KB 수정은 `PATCH /api/kb/{id}` API를 사용한다.
- KB를 목록에서 제거해도 실제 DB에서 삭제되지 않는다. KB 삭제는 `DELETE /api/kb/{id}` API로 명시적으로 수행한다.
- 환경별로 KB 구성이 달라야 하면 `docker/settings.yaml`을 환경별로 분리하거나 환경변수 오버라이드를 활용한다.

---

## 14. mcp

Model Context Protocol 서버 설정. AI 에이전트가 rag-api를 툴로 사용할 수 있게 한다.

```yaml
mcp:
  enabled: true
  transport: streamable-http
```

| 키 | 기본값 | 설명 |
|----|--------|------|
| `enabled` | `true` | MCP 엔드포인트 활성화 여부 |
| `transport` | `streamable-http` | `stdio` / `sse` / `streamable-http` |

**운영 고려사항**

- `streamable-http`는 HTTP 기반으로 서버 재시작 없이 클라이언트가 재연결할 수 있다. VS Code, Claude Desktop 등 대부분의 MCP 클라이언트가 지원한다.
- `stdio`는 단일 프로세스 환경(CLI 실행)에서만 유용하다. 서버 모드로 배포할 때는 사용하지 않는다.
- `enabled: false`로 설정하면 `/mcp` 경로가 비활성화된다. MCP를 사용하지 않는 배포에서는 불필요한 엔드포인트를 닫는 용도로 사용한다.

---

## 15. tracing

Langfuse 기반 LLM 추적 설정. 임베딩 호출 및 검색 파이프라인의 trace를 기록한다.

```yaml
tracing:
  enabled: true
  langfuse_baseurl: "http://langfuse-web.llm.svc.cluster.local:3000"
  langfuse_public_key: "pk-lf-..."
  langfuse_secret_key: "sk-lf-..."
  service_name: "rag-api"
```

| 키 | 설명 |
|----|------|
| `enabled` | `false`로 설정하면 Langfuse 클라이언트를 초기화하지 않음 |
| `langfuse_baseurl` | Langfuse 서버 주소 |
| `langfuse_public_key` | Langfuse 프로젝트 퍼블릭 키 |
| `langfuse_secret_key` | Langfuse 프로젝트 시크릿 키 |
| `service_name` | Langfuse trace에 표시되는 서비스 이름 |

**운영 고려사항**

- `enabled: false`이면 Langfuse 서버가 없어도 정상 동작한다. Langfuse 없이 배포할 때는 반드시 `false`로 설정한다. `true`인 상태에서 서버가 없으면 추적 전송 시 연결 오류가 로그에 반복 출력될 수 있다.
- `langfuse_secret_key`는 `TRACING__LANGFUSE_SECRET_KEY` 환경변수로 주입한다.
- `service_name`은 동일 Langfuse 프로젝트에 여러 서비스가 연결될 때 trace를 구분하는 레이블이다.

---

## 16. logging

애플리케이션 로그 레벨 설정.

```yaml
logging:
  level: INFO
```

| 값 | 설명 |
|----|------|
| `DEBUG` | 모든 내부 처리 로그. 파이프라인 각 단계 입출력 포함 |
| `INFO` | 일반 운영 로그. 문서 처리 시작·완료, API 요청 기록 |
| `WARNING` | 비정상 상황이지만 처리는 계속되는 경우 |
| `ERROR` | 처리 실패, 예외 발생 |

**운영 고려사항**

- `DEBUG`는 로그 볼륨이 크게 늘어난다. 트러블슈팅 이후에는 반드시 `INFO`로 되돌린다.
- `WARNING` 이상의 로그는 반드시 원인을 확인한다. `WARNING`은 MinIO delete 실패처럼 의도된 silent-fail 케이스에도 출력된다.
- 로그 레벨은 환경변수(`LOGGING__LEVEL=DEBUG`)로도 변경 가능하므로 재배포 없이 런타임 조정이 필요한 경우 활용한다. 단, 재시작 없이 반영되는 것은 아니며 환경변수 주입 후 컨테이너 재시작이 필요하다.

---

## 부록: 환경변수 오버라이드 규칙

Pydantic Settings는 환경변수를 자동으로 인식한다. 중첩 설정은 `__`로 구분한다.

```bash
# 단순 키
LOGGING__LEVEL=DEBUG

# 중첩 키
EMBEDDING__PROVIDER=openai
EMBEDDING__OPENAI_API_KEY=sk-...
RETRIEVAL__RERANK__ENABLED=true
POSTGRES__PASSWORD=prod-password

# 인프라 연결
QDRANT__HOST=qdrant.internal
REDIS__PASSWORD=secure-password
S3__SECRET_KEY=minio-secret
```

환경변수는 `settings.yaml` 값보다 우선 적용된다.
