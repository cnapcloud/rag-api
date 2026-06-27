# 문서 중복·갱신 감지 파이프라인 디자인

## 1. 개요

신규 문서 유입 시 기존 문서와의 관계를 분석하여 중복 문서 감지, 문서 갱신 여부 판별, 관련 문서 연결을 수행하는 파이프라인이다.
문서 간 관계를 동일·유사·관련·무관으로 분류하며, 판정 결과에 따라 색인 스킵, 기존 문서 갱신, 신규 문서 추가 등의 후속 처리를 자동화한다.
이를 통해 불필요한 재처리를 줄이고 RAG 인덱스의 일관성과 검색 품질을 유지한다.

---

## 2. 전체 파이프라인 구조

파이프라인은 성격이 다른 두 레이어로 구성된다.

- **탐지 레이어 (1·2단계):** "비교할 가치가 있는 후보가 존재하는가"를 찾는 레이어
- **정밀화 레이어 (3·4단계):** 탐지 레이어에서 확정된 후보에 대해 벡터스토어로 확인하고 LLM에 판단까지 요청하는 점점 정밀하고 비싼 방법

```
신규 문서 A 입력
    │
    ▼
══════════ 탐지 레이어 (독립적 방법, 비용 오름차순) ══════════
    │
    ▼
[1단계] 해시 기반 비교 (제목 SHA-256 + 본문 SimHash)
    │
    ├─ 본문 Hamming Distance ≈ 0 (본문이 사실상 동일)
    │      → 제목도 일치하면 "동일", 제목만 다르면 "제목변경" 
    │        (2·3·4단계 모두 스킵, 5단계로 직행)
    │                                              
    └─ 그 외 (제목/본문 중 하나만 느슨히 일치, 또는 둘 다 불일치)
            │
            ▼
     1단계에서 후보 발견?
            │
      ┌─────┴─────┐
     YES           NO
      │             │
      │             ▼
      │      [2단계] 경량 알고리즘 비교 (Jaccard + Jaro-Winkler)
      │      1단계와 무관하게 별도 방식으로 코퍼스 재탐색
      │             │
      │       ┌─────┴─────┐
      │      YES           NO
      │       │             │
      └───┬───┘             ▼
          │            "무관" 확정 ───────────────────────┐
          ▼                                             │
   근접 중복 후보 C 확보 (복수 가능)                          │
          │                                            │
          ▼                                            │
══════════ 정밀화 레이어 (확정된 A-C 페어를 체이닝하며 정밀 검증) ══════════
          │                                            │
          ▼                                            │
[3단계] 청크 단위 비교                                     │
   3-1) 청크 해시 비교 → 동일 청크는 재임베딩(스킵)             │
   3-2) 임베딩 코사인 유사도 비교 → 문서 레벨 집계 점수 산출       │
          │                                            │
          ▼                                            │
[4단계] 관계 유형 판정                                      │
   집계 점수 임계값 1차 판정 (동일/유사/관련/무관)               │
   "유사" 구간만 LLM 호출로 최종 확정                         │
          │                                            │
          ▼                                            │
   최종 판정 (동일/유사/관련/무관)                            │
   ※ 후보 C가 여러 개면 각 C에 대해 반복                      │
          │                                            │
          ▼                                            ▼
[5단계] 판정 결과별 후속 처리 ◀──────────────────────────────┘
   동일→색인 스킵 / 제목변경→제목·원본 키 갱신 / 유사→기존 문서 갱신 / 관련→링크 메타데이터 추가 / 무관→신규 색인
```

---

## 2.1 파이프라인 구성 방안

### 실행 구조

dedup 파이프라인은 두 가지 방식으로 실행된다.

**ingest 흐름 (주 경로):**
기존 `ingest_job` 내 `dedup_op` 하나로 통합한다.
`dedup_op`은 내부에서 `run_dedup_pipeline()`을 동기 호출하여 1~5단계 전체를 처리한 뒤 결과를 반환받는다.
Dagster는 `dedup_op`이 완료될 때까지 하위 op을 실행하지 않으므로, 별도 완료 감지 메커니즘이 필요 없다.

**독립 실행 (백필 / 수동 재처리):**
`dedup_job`은 동일한 dedup 단계를 Dagster op(`simhash_op` → `verdict_op`)으로 노출한 별도 job이다.
센서/스케줄에서 자동 트리거되지 않으며, 운영자가 수동으로 실행하거나 백필 스크립트에서 호출한다.
두 방식 모두 `pipeline/ops/dedup/` 의 동일한 순수 함수를 공유한다.

### 단계 책임 분리

`run_dedup_pipeline()`이 1~5단계를 모두 담당한다.

- 1~4단계: 판정 수행
- 5단계: 판정 결과별 후속 처리(Qdrant payload 갱신, Redis 상태 변경, 링크 메타데이터 추가 등)를 `run_dedup_pipeline()` 내부에서 완결

`dedup_op`은 `run_dedup_pipeline()` 반환값의 `needs_indexing` 여부만 확인하여 하위 op 실행 여부를 결정한다.

### 분기 처리

**DedupResult 필드**

| 필드 | 타입 | 의미 |
|------|------|------|
| `body_match` | `identical_level` / `similar` / `none` | 본문 유사도 판정 |
| `title_match` | `same` / `changed` / `unknown` | 제목 일치 여부 (1단계만 판정) |
| `duplicate_doc_id` | `str \| None` | 후보 중 best match 1건 (verdict 처리 대상) |
| `candidate_doc_ids` | `list[str]` | 임계값을 통과한 전체 후보 목록 (best match 포함) |
| `needs_indexing` | `bool` | verdict 처리 후 색인 파이프라인 진입 여부 |

`candidate_doc_ids`에는 LSH 조회 결과 전체가 아닌, 임계값(Hamming 또는 Jaccard/제목)을 실제 통과한 것만 포함된다.
`run_verdict` 진입 시 `candidate_doc_ids`와 `duplicate_doc_id`를 INFO 로그로 기록하며, 실제 처리는 `duplicate_doc_id` (best match) 단건에만 적용한다.

**Verdict 구성 요소**

| 차원 | 값 | 판정 기준 |
|------|-----|----------|
| body | `identical` | SimHash Hamming ≤ hamming_identical_threshold (1단계) |
| body | `similar` | SimHash Hamming ≤ hamming_similar_threshold (1단계) 또는 MinHash Jaccard ≥ jaccard_threshold (2단계) |
| body | `none` | 후보 없음 |
| title | `identical` | SHA-256 완전 일치 (1단계) |
| title | `similar` | pg_trgm similarity ≥ title_fuzzy_threshold (2단계) |
| title | `none` | 불일치 |

**Verdict 결합 규칙**

| body | title | verdict | to_chunk |
|------|-------|---------|----------|
| identical | identical | `identical` | False |
| identical | similar/none | `title_changed` | False |
| similar | any | `similar` | False |
| none | — | `proceed` | True |

**후속 처리**

| verdict | C 처리 | A 처리 |
|---------|--------|--------|
| `identical` | 변경 없음 | dedup_skipped |
| `title_changed` | outdated + Qdrant payload 갱신 + simhash_bands 삭제 | indexed (신규 색인) |
| `similar` | outdated | indexed (신규 색인) |
| `proceed` | — | indexed (신규 색인) |

> **1·2단계 구현 기간 (현재):** `similar` verdict는 to_chunk=False로 C를 outdated 처리하고 A를 신규 색인한다. 3단계 구현 시 `similar`를 auto-skip 대신 임베딩 정밀 비교로 라우팅하도록 변경한다.

`needs_indexing=True` 경우, `run_dedup_pipeline()`이 C측 처리(기존 문서 상태 갱신 등)를 완결한 뒤 반환하며, 이후 표준 색인 파이프라인(chunk → embed → upsert → meta)이 A를 신규 색인한다.

### 동시성 제어

1단계 "SUNION 조회 → SADD 등록" 구간의 race condition 방지를 위해 SimHash 밴드 키 단위 Redis 락을 사용한다. 상세 내용은 3.1.3 참조.

---

## 3. 단계별 개발 요건

## 3.1 [1단계] 문서 레벨 해시 비교
 
**목적:** 완전 동일 문서 및 미세 변경(오타/공백/약간의 수정) 문서를 최저 비용으로 즉시 식별한다.
 
**입력**
- 신규 문서 A (제목, 본문)
**전제 조건**
- 기존 문서 전체에 `title_hash`(SHA-256)와 본문 SimHash가 사전 계산·색인되어 있어야 함 (SimHash는 4조각 분할 후 `simhash_band:*` Redis Set에 등록)
**처리**
 
```
신규 문서 A 입력
    │
    ├──────────────┐
    ▼              ▼
[제목 비교]      [본문 비교]
SHA-256 해시     SimHash 생성
완전 일치 비교    + Hamming Distance 비교
    │              │
    └──────┬───────┘
           ▼
   본문 Hamming Distance ≈ 0 ?
           │
     ┌─────┴─────┐
    YES           NO
     │             │
     ▼             ▼
제목도 일치?    제목 일치 OR 본문거리 임계값 이내?
     │              ┌─────┴─────┐
 ┌───┴─────┐       YES          NO
YES        NO       │           │
 │         │        ▼           ▼
 ▼         ▼   "동일 후보"    2단계로 진행
"동일"   "제목변경"  3단계 전달
 └────┬────┘
      ▼
 5단계 직행 (2·3·4단계 스킵)
```
 
**3.1.1 제목 비교 (SHA-256 완전 일치)**
- 제목 해시 생성 + 기존 문서 `title_hash` 백필
- 신규 문서 해시 계산 → 조회·비교, 완전 일치 시 "제목 동일" 플래그
**3.1.2 본문 비교 (SimHash + Postgres band 인덱스)**

```
Postgres 테이블: simhash_bands (band_id, doc_id, kb_id, band_index, band_value)

[사전 작업] 기존 문서마다 SimHash 계산 → 4조각 분할 → simhash_bands에 INSERT

[신규 문서 유입]
SimHash 계산 → 4조각 분할
    ↓
4개 (band_index, band_value) 쌍을 OR 조건으로 한 번에 조회
(조각 1개라도 일치 → 후보, OR조건)
    ↓
후보 doc_id 추출 (자기 자신 제외) → documents 테이블에서 content_simhash 일괄 조회
    ↓
후보만 정밀 Hamming Distance 계산 → 임계값 이내만 최종 후보
    ↓
신규 문서 조각도 동일하게 INSERT (다음 비교 대상이 되도록)
```

- 본문 shingle: character-level n-gram, n=3 (한국어·영어 동일 처리, 공백 포함)
- SimHash 비트 길이: 64bit, 4밴드(밴드당 16bit)
- `content_simhash`는 Postgres BIGINT(i64)로 저장 — Hamming 비교 시 u64로 복원

**3.1.3 동시성**

Postgres 트랜잭션 격리로 band 조회와 INSERT가 직렬화된다.
동시 유입된 근접 중복 문서가 서로를 탐지하지 못할 수 있으나, 이는 허용 범위의 best-effort 동작이다.
(이전 Redis 밴드 락은 제거됨)

**출력**

| Hamming Distance | 제목 | verdict |
|-----------------|------|---------|
| ≤ hamming_identical_threshold (3) | SHA-256 일치 | `identical` |
| ≤ hamming_identical_threshold (3) | SHA-256 불일치 | `title_changed` |
| ≤ hamming_similar_threshold (10) | any | `similar` |
| > hamming_similar_threshold | — | 2단계로 진행 |
| 후보 없음 | — | 2단계로 진행 |

**완료 기준**
- `identical`/`title_changed`/`similar` 케이스가 2단계 스킵하고 5단계로 직행
- 전체 스캔 없이 4개 키 SUNION만으로 후보 추출됨을 확인

**결정 사항**
- n-gram: character-level n=3 (한국어·영어 동일, 공백 포함)
- hamming_identical_threshold: 3 (body:identical 기준)
- hamming_similar_threshold: 10 (body:similar 기준, 초과 시 2단계로)

**오픈 이슈**
- 문서 규모 확대 시 Postgres 이전 시점/기준 미정
- band 키 SCARD 모니터링 임계치 미정

---

### 3.2 [2단계] 경량 알고리즘 기반 후보 필터링

**목적:** 임베딩 계산 전, 비교할 가치가 없는 후보를 저비용으로 제거한다.

**입력**
- 신규 문서 A — 1단계(해시 비교)에서 후보를 찾지 못한 경우에만 실행. 코퍼스 전체를 토큰 기반으로 독립 재탐색

**처리**

1) 토큰화
- Kiwi 형태소 분석기 사용 (명사/동사·형용사 어간만 추출, 조사/어미 제거)
- 정규화: 영문 소문자화, 전각/반각 통일, 마크다운 문법 제거, 코드블록 제외

2) Jaccard 유사도 (본문) — MinHash 방식
- 토큰 원문을 저장하지 않고 **MinHash 서명(128개 해시값, 512바이트 고정)** 으로 압축하여 Postgres `doc_minhash_bands` 테이블에 저장
  - 인제스트 시 형태소 분석 → MinHash 128개 산출 → 16밴드 × 8행 분할 → 저장 (문서당 512바이트, 10만 문서 기준 약 51MB)
  - 비교 시 A의 밴드값으로 DB 조회 → 밴드 하나라도 일치하는 문서만 후보 추출 → 후보에 대해 `Jaccard 근사값 = 일치하는 해시 수 / 128` 계산 (오차 ±0.09)
  - P(min_hash(A) == min_hash(B)) = Jaccard(A,B) — 최솟값 일치 확률이 Jaccard와 수학적으로 동치이므로 "Jaccard 근사"라 부름
- SimHash(`simhash_bands`)와 동일한 밴드 조회 패턴, 나란히 관리

  | | SimHash (1단계) | MinHash (2단계) |
  |---|---|---|
  | 계산 방식 | 토큰별 해시 비트를 TF 가중 투표 → 64비트 지문 | 128개 해시 함수로 토큰 집합의 최솟값 추출 → 128개 서명 |
  | 비교 방식 | XOR → Hamming 거리 | 동일 위치 일치 수 / 128 |
  | 근사 대상 | 코사인 유사도 | Jaccard 유사도 |
  | 탐지 대상 | 거의 동일한 문서 — 문자 n-gram 변화 최소 | 내용어가 20% 이상 겹치는 문서 — 문장 구조 달라도 탐지 가능 |

3) 퍼지 매칭 (Jaro-Winkler, 제목 한정)
- 제목에만 적용 (본문은 Jaccard로 충분히 커버, 연산비용 큼). 예외: 본문 길이 < 컷오프(예: 200자) 단문은 본문에도 적용
- Levenshtein 대신 Jaro-Winkler 채택 (접두사 가중 → 버전/수정 suffix 패턴 탐지에 적합)
- 후보 탐색: 전수 조사 없이 `pg_trgm` GIN 인덱스 사용
  - `documents.title` 컬럼에 trigram 인덱스 생성 (인제스트 시 별도 저장 불필요, PostgreSQL이 자동 관리)
  - `WHERE similarity(title, $1) > title_fuzzy_threshold` 쿼리로 후보 추출
  - MinHash 밴드 조회(본문)와 pg_trgm 조회(제목) 결과를 합집합으로 통합 → 4) 임계값 판정 진행

4) 임계값 판정 (3분기)

| 조건 | 판정 |
|---|---|
| Jaccard ≥ jaccard_threshold | 통과 |
| Jaccard < jaccard_threshold, 제목유사도 ≥ title_fuzzy_threshold, Jaccard ≥ title_only_min_jaccard_floor | 통과 |
| Jaccard < jaccard_threshold, 제목유사도 ≥ title_fuzzy_threshold, Jaccard < title_only_min_jaccard_floor | 무관 즉시 확정 (3단계 스킵 → 5단계 직행) |
| 둘 다 미달 | 무관 확정 (3단계 스킵 → 5단계 직행) |

- 임계값은 config(yaml/json) 분리, 하드코딩 금지 — settings.yaml `dedup` 섹션에 배치
- 초기값 및 근거:

  | 변수 | 1+2단계만 운영 시 | 3단계 이후 추가 시 | 근거 |
  |------|------------------|-------------------|------|
  | `jaccard_threshold` | 0.65 | 0.2 | 1+2단계만: 2단계가 최종 판정이므로 오탐 방지를 위해 높게 설정. 3단계 추가 시: 이후 정밀 검증이 있으므로 후보를 넉넉히 넘김 |
  | `title_fuzzy_threshold` | 0.85 | 0.7 | 1+2단계만: 매우 유사한 제목만 통과. 3단계 추가 시: 버전/날짜 suffix 패턴(보고서_2024Q1 → 보고서_2024Q2)까지 포함해 느슨하게 |
  | `title_only_min_jaccard_floor` | 0.25 | 0.05 | 1+2단계만: 제목 유사 경로에서도 본문 25% 이상 겹쳐야 통과. 3단계 추가 시: 5% 최소 겹침으로 완화 |

- 모든 판정(통과/제외/무관즉시확정) 점수는 로그 기록 (임계값 튜닝용)

**출력**
- 임계값 통과 후보 문서 목록 `candidate_doc_ids` (C1, C2, ... Cn — 복수 가능) — LSH 조회 결과 전체가 아닌, Jaccard/제목 임계값을 실제로 통과한 것만 포함
- `duplicate_doc_id` — 통과 후보 중 Jaccard가 가장 높은 best match 1건
- 무관 즉시 확정 문서 → 3단계 스킵, 5단계(신규 색인) 직행
- 판정 점수 로그

**완료 기준**
- 명백히 무관한 문서가 3단계까지 넘어가지 않음
- 제목만 우연히 비슷하고 본문이 무관한 경우, title_only_min_jaccard_floor에서 차단됨

**오픈 이슈**
- **(운영 후)** 초기값은 설계 근거 기반으로 설정됨 — 운영 데이터(오탐/누락 판정 로그) 기반 튜닝 필요
- **(운영 후)** 임계값 튜닝용 라벨 데이터셋은 사전 구축 없이 운영 중 오탐/누락 사례로 점진 구축 (목표 50~100쌍)


---

### 3.3 [3단계] 청크 단위 정밀 비교
[TODO]

### 3.3.2 임베딩 기반 코사인 유사도 비교 및 문서 레벨 점수 산출

**목적:** A의 각 청크와 후보 문서 C의 청크들 간 코사인 유사도를 비교하여, 청크 단위 매칭 목록과 문서 레벨 집계 점수를 산출한다.

**입력**
- A doc_id (청크별 임베딩 벡터)
- C doc_id (이전 단계에서 선별된 후보)
- threshold = **0.50** (3.4 점수구간표의 "무관" 경계와 동일하게 맞춤 — 이 값 미달은 매칭 목록에서 자동 제외되어 별도 분류 불필요)

**처리**

1. A의 각 청크별로 C의 청크들을 대상으로 벡터스토어 조회 (top_k 후보 조회)
2. top_k 결과 중 threshold(0.50) 이상인 것만 필터링
3. 필터링된 후보 중 **score가 가장 높은 것 1개만 선택** (Top-1) — A 청크 하나당 매칭은 0개 또는 1개로 정리
4. 위 과정을 A의 모든 청크에 대해 반복 → (A_청크, C_청크, score) 매칭 목록 생성 (모든 score는 0.50 이상)
5. 문서 레벨 집계 점수 산출: 매칭 목록의 score들을 집계하여 (A doc_id, C doc_id) 쌍 단위 점수 1개 산출

**출력**
- 매칭 목록: (A_청크, C_청크, score) — A 청크당 최대 1개, 전부 ≥0.50
- 문서 레벨 집계 점수: (A doc_id, C doc_id, score) → 3.4 전달

**완료 기준:** 모든 A 청크에 대해 C측 매칭이 0개 또는 1개로 정리되고, 문서 레벨 집계 점수가 산출됨을 확인

**오픈 이슈**
- 집계 방식(평균 / 가중평균 / 최댓값) 미정

---

### 3.4 [4단계] 관계 유형(동일/유사/관련/무관) 판정

**목적:** 청크 매칭 쌍들의 점수 구간 분포 비율을 기준으로 A-C 관계를 확정한다.

**입력**
- A doc_id, C doc_id
- 3.3.2 출력: 문서 레벨 집계 점수, threshold 통과 (A_청크, C_청크, score) 매칭 목록

**처리**

1) 청크 쌍별 구간 판정

| 점수 구간 | 판정 |
|---|---|
| ≥0.95 | 동일 |
| 0.75~0.95 | 유사 |
| 0.50~0.75 | 관련 |
| <0.50 | 무관 |

2) 비율 산출
- 분모 N = A 전체 청크 수
- 동일비율 = 동일구간 매칭쌍 개수 / N
- 유사비율 = 유사구간 매칭쌍 개수 / N
- 관련비율 = 관련구간 매칭쌍 개수 / N

3) 문서 레벨 1차 판정 (비율 기반, 상위 구간부터 확인)

| 조건 | 판정 | LLM 호출 |
|---|---|---|
| 동일비율 ≥ R0(80%) | 동일 | 불필요 |
| 동일비율<R0, (동일비율+유사비율) ≥ R1(20%) | — | 필요 |
| (동일비율+유사비율)<R1, 관련비율 ≥ R1′(10%) | 관련 | 불필요 |
| 위 모두 미달 | 무관 | 불필요 |

4) LLM 호출 (대상인 경우만)
- 입력: 동일+유사구간 매칭쌍의 A 청크 + 매칭된 C 청크
- 출력: 쌍별 판정(동일/유사/관련/무관) + 근거 1줄

5) LLM 응답 집계 → 최종 판정
- M = LLM 호출된 쌍 개수
- 응답 라벨별 개수: m_동일 / m_유사 / m_관련 / m_무관

| 조건 | 최종 판정 |
|---|---|
| m_동일/M ≥ R2a(70%) | 동일 |
| (m_동일+m_유사)/M ≥ R2(50%) | 유사 |
| m_관련/M ≥ R2′(30%) | 관련 |
| 위 모두 미달 | 무관 |

**출력**
- (A doc_id, C doc_id, 최종 판정, 근거, 사용된 비율값) → 3.5 전달

**완료 기준**
- 비율 기반 1차 판정과 LLM 응답 집계 판정이 일관되게 산출됨
- 평가 데이터셋으로 임계치 검증 가능

**오픈 이슈**
- R0(80%)/R1(20%)/R1′(10%)/R2a(70%)/R2(50%)/R2′(30%) 전부 초기 default — 데이터셋 기반 검증 필요
- M(LLM 호출 건수)이 너무 작으면 비율 산정 방식에 왜곡이 생김 (최소 건수 기준 미정)

---

### 3.5 [5단계] 판정 결과별 후속 처리

**목적:** 판정 라벨별로 색인/상태 갱신을 자동 처리한다.

**입력**
- 1단계 직행: (A doc_id, C doc_id, 판정 ∈ {동일, 제목변경}, 근거) — 2·3·4단계 스킵
- 4단계 경유: (A doc_id, C doc_id, 판정 ∈ {동일, 유사, 관련, 무관}, 근거)

**처리 정책**

| 판정 | 처리 |
|---|---|
| 동일 | A: dedup_skipped. C 변경 없음 |
| 제목변경 (A 최신) | Qdrant payload(title/source) 갱신 + C: outdated + simhash_bands 삭제 + A: indexed. 재임베딩 없음 |
| 제목변경 (A 구버전) | A: outdated. C 변경 없음 |
| 유사 | A 신규 색인 + C를 outdated 전환 (상태 필드 갱신) |
| 관련 | A 신규 색인 + 관련 링크 메타데이터 추가 |
| 무관 | A 신규 색인 |

**다중 후보(C1, C2...) 동시 매칭 시 우선순위 규칙**

A가 여러 후보와 동시에 매칭되어 후보별로 다른 판정을 받을 수 있음. 처리 순서는 다음과 같이 확정:

1. **동일이 하나라도 존재 → 최우선 적용**
   - A 색인 자체를 스킵 (다른 후보들의 유사/관련 판정과 무관하게 무조건 우선)
   - 동일 판정된 C(예: C1)를 대표 entity로 삼아, 다른 후보(C2 등)의 supersede/related 대상을 A 대신 **C1로 재배선**
   - 근거: "동일"은 A=기존 데이터라는 의미라 신규 색인을 전제로 하는 다른 판정(유사/관련)과 양립 불가능하므로 무조건 우선
2. **동일이 없으면 → 유사/관련/무관은 배타적이지 않으므로 누적 적용**
   - A는 1회만 색인 (공통 베이스 액션)
   - 유사로 매칭된 모든 C → 각각 deprecated 전환 + supersedes 목록에 추가
   - 관련으로 매칭된 모든 C → 각각 관련 링크 목록에 추가
   - 무관으로 매칭된 C → 별도 액션 없음 (무시)

**"유사" 처리 — 상태 필드 기반 라이프사이클**

1. A 신규 색인 (C 데이터는 불변)
2. C 갱신: status active→deprecated, deprecated_at 기록, superseded_by=A
3. A 갱신: supersedes=C
4. 검색 쿼리에 status=active 필터 항상 적용
5. 그레이스 기간(N일, 미정) 후 cleanup job이 deprecated 항목 삭제

**상태 필드**
- status (active / deprecated / deleted)
- created_at
- deprecated_at (deprecated 진입 시만 존재)
- deleted_at
- superseded_by / supersedes

**동기화 원칙:** Qdrant(source of truth) 갱신 확인 후 Redis 갱신 — 역순 금지

**롤백:** 그레이스 기간 내 C↔A의 status 재전환만으로 즉시 복구 (재임베딩 불필요)

**"제목변경" 처리 — doc_created_at 기반 최신 판단**

A, C의 `doc_created_at` 비교:
- C의 `doc_created_at`이 NULL이면 A를 최신으로 간주

A가 최신인 경우:
1. Qdrant: C의 모든 청크 payload `title`, `source` → A 값으로 갱신
2. Postgres C: `status` → `outdated`
3. Postgres `simhash_bands`: C 행 삭제
4. Postgres A: `status` → `indexed`, `process_finished_at` 갱신

A가 구버전인 경우:
1. Postgres A: `status` → `outdated`, `error` → `dedup:title_changed duplicate_of={C.doc_id}`

오픈 이슈:
- MinIO 파일 삭제 (C의 구버전 파일, grace period 방식) — 별도 US

**출력**
- 색인/갱신/링크 처리 완료 상태
- 처리 이력 레코드 1건

**완료 기준**
- 판정별 자동 처리 동작 + 이력 조회 가능
- "유사" 케이스에서 검색 결과가 A만 노출됨을 확인
- 다중 후보 매칭 시 동일 우선 규칙대로 재배선되어 처리됨을 확인

**오픈 이슈**
- 그레이스 기간(N일), cleanup 주기 미정
- Qdrant-Redis 동기화 실패 시 보정 메커니즘 미정
- 다중 "유사" 매칭 시 전체 deprecated(다중 supersedes) 허용 여부, 또는 최고점 1개만 적용할지 미정
- "관련" 링크 단방향/양방향 미정
- 제목변경 M값, history 보관기간 미정

## 4. 처리 순서 및 동시성

**구현 완료 — 파이프라인 순서 고정:** 문서 업로드 → dedup 판정(parse → simhash → verdict) → (필요한 경우에만) 임베딩 파이프라인(표준 색인). `ingest_job`에서 `parse_op → dedup_op → chunk_op` 순서로 강제되며, "동일"·"제목변경" 판정 시 `dedup_op`이 `to_chunk` Output을 emit하지 않아 이후 단계가 실행되지 않는다. "임베딩이 dedup보다 먼저 실행"되는 문제는 순서 자체로 해소됨.

**구현 완료 — 동시 처리:** SimHash band 조회와 INSERT가 Postgres 트랜잭션 내에서 처리된다. Redis 밴드 락은 제거되었으며, 극단적 동시 유입에서의 중복 탐지 누락은 best-effort로 허용한다.

**구현 완료 — 재인덱싱(backfill) 시 순서 의존성:** `handle_title_changed`에서 처리 순서가 아닌 `doc_created_at` 값을 직접 비교해 신구를 판단하므로, 백필 실행 순서와 무관하게 항상 동일한 결과를 낸다.

**오픈 이슈**
- [ ] 레이스 컨디션으로 누락된 중복을 사후에 잡아내는 주기적 정합성 점검 배치 여부 미결정

---

## 5. Dev Requirements (backlog units)

D-01과 D-02는 구현 완료. 각 항목은 독립적으로 구현 가능하며, 3단계(D-04)는 2단계(D-03) 없이도 구현할 수 있으나 2단계가 없으면 모든 문서가 임베딩 비교까지 진행된다.

| ID | Title | Status | Depends on |
|---|---|---|---|
| D-01 | 1단계: SHA-256 title hash + SimHash 본문 비교, Postgres simhash_bands 인덱스, `동일`/`제목변경`/`similar` 5단계 직행 | done | — |
| D-02 | 5단계: `동일`/`제목변경` 후속 처리 — `doc_created_at` 기준 신구 판단, Qdrant payload 갱신, `outdated`/`duplicate_of` 기록, simhash_bands 삭제 | done | D-01 |
| D-03 | 2단계: MinHash Jaccard(본문) + pg_trgm(제목) 경량 필터링 — Kiwi 형태소, 밴드 인덱스 조회, 임계값 config 분리, 3분기 판정, `similar` verdict | done | D-01 |
| D-04 | 3단계: 청크 단위 임베딩 코사인 유사도 비교, threshold 0.50 필터, Top-1 매칭, 문서 레벨 집계 점수 산출 | todo | D-02 |
| D-05 | 4단계: 비율 기반 1차 판정 (동일/유사/관련/무관) + `유사` 구간 LLM 최종 확정, 다중 후보 C 반복 처리 | todo | D-04 |
| D-06 | 5단계 `유사`: A 신규 색인 + C `status=deprecated`, `superseded_by`/`supersedes` 필드, `status=active` 검색 필터 | todo | D-05 |
| D-07 | 5단계 `관련`: A 신규 색인 + 관련 링크 메타데이터 추가 | todo | D-05 |
| D-08 | 5단계 다중 후보 배선: `동일` 판정 최우선 적용, 나머지 C 배선 재조정 규칙 | todo | D-06, D-07 |
| D-09 | Cleanup job: 그레이스 기간 경과 `deprecated` 문서 삭제 (주기/기간 미정) | todo | D-06 |
| D-10 | MinIO 구버전 파일 삭제: `outdated` 문서 원본 파일 정리 (grace period 방식) | todo | D-02 |

Recommended implementation order: D-01 (done) → D-02 (done) → D-03 → D-04 → D-05 → D-06 + D-07 (병렬) → D-08 → D-09 + D-10 (병렬)
