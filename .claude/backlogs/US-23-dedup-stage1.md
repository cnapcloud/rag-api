# US-23: Dedup Stage 1 — 해시 기반 중복 감지

**상태**: done

> 설계: [dedup.md](../../docs/internal/design/dedup.md) (D-01, D-02)

## 목적

신규 문서 유입 시 제목 SHA-256 + 본문 SimHash를 이용해 완전 동일 문서와 제목 변경 문서를
최저 비용으로 즉시 감지한다. 감지된 경우 색인을 스킵하거나 기존 문서 메타데이터를 갱신한다.

## 범위

- SimHash 탐지(simhash.py) 구현
- 탐지 결과에 대한 verdict 처리 (identical / title_changed)
- title_changed 케이스 5단계 처리 (Qdrant payload 갱신, 상태 전환, simhash_bands 삭제)
- 전체 코퍼스 SimHash 백필은 이번 범위 밖

## 비범위

- stages 2~4 (Jaccard, 코사인 유사도, LLM 판정)
- 기존 문서 SimHash 백필 스크립트
- title_changed 케이스 MinIO 파일 삭제 (별도 US)

## 구현 항목

### 신규 파일

- `src/pipeline/ops/dedup/__init__.py` — `run_simhash_detection`, `run_verdict` export
- `src/pipeline/ops/dedup/types.py` — `DedupResult` dataclass
- `src/pipeline/ops/dedup/simhash.py` — SimHash + 제목 해시 + Redis 밴드 락/조회/등록
- `src/pipeline/ops/dedup/verdict.py` — 해시 저장 + identical/title_changed 판정 처리
- `tests/unit/test_dedup_simhash.py` — simhash 단위 테스트
- `tests/unit/test_dedup_verdict.py` — verdict 단위 테스트

### 수정 파일

- `settings.yaml` — `dedup:` 섹션 추가
- `src/config/settings.py` — `DedupSettings` 추가
- `src/pipeline/ops/dedup/__init__.py` — `run_dedup_pipeline()` 추가 (1단계 오케스트레이터)
- `src/defs/ops/ingest_ops.py` — `dedup_op` 단일 op 추가
- `src/defs/ops/dedup_ops.py` — **신규**: `simhash_op` + `verdict_op` (dedup_job 전용 Dagster 래퍼)
- `src/defs/jobs/ingest_job.py` — `validate_op` 다음에 `dedup_op` 삽입
- `src/defs/jobs/dedup_job.py` — **신규**: 독립 실행용 Dagster job
- `src/pipeline/ops/runner.py` — `run_dedup_pipeline()` 호출로 단순화
- `src/infra/postgres.py` — `source_uri` 업데이트 허용, `delete_simhash_bands()` 추가
- `src/infra/qdrant.py` — `update_payload_by_doc_id()` 추가

## 파이프라인 흐름

```
[ingest_job — 주 경로]
validate_op → dedup_op → parse_op → chunk_op → embed_op → upsert_op → meta_op
                  │
      run_dedup_pipeline() 동기 호출 (1단계 SimHash, 향후 2~5단계 추가)
      needs_indexing=False → 파이프라인 종료
      needs_indexing=True  → to_parse 전달

[dedup_job — 독립 실행용: 백필 / 수동 재처리]
simhash_op → verdict_op
```

## DedupResult 필드 (1단계 기준)

`candidate_doc_ids`: Hamming ≤ hamming_similar_threshold를 통과한 전체 후보 (거리 오름차순 정렬).
`duplicate_doc_id`: 후보 중 Hamming 거리가 가장 낮은 best match 1건 (verdict 처리 대상).
`run_verdict` 진입 시 두 필드를 INFO 로그로 기록하며, 실제 처리는 `duplicate_doc_id` 단건에만 적용한다.

## Verdict 구성 요소

| 차원 | 값 | 판정 기준 |
|------|-----|----------|
| body | `identical` | SimHash Hamming ≤ hamming_identical_threshold (3) |
| body | `similar` | SimHash Hamming ≤ hamming_similar_threshold (10) |
| title | `identical` | SHA-256 완전 일치 |

## Verdict 결합 규칙 (1단계)

| body | title | verdict | to_chunk |
|------|-------|---------|----------|
| identical | identical | `identical` | False |
| identical | 불일치 | `title_changed` | False |
| similar | any | `similar` | False |
| Hamming > similar_threshold 또는 후보 없음 | — | 2단계로 진행 | — |

## Verdict 처리 정책

| verdict | C 처리 | A 처리 |
|---------|--------|--------|
| `identical` | 변경 없음 | dedup_skipped |
| `title_changed` (A 최신) | outdated + Qdrant payload 갱신 + simhash_bands 삭제 | indexed |
| `title_changed` (A 구버전) | 변경 없음 | outdated |
| `similar` (A 최신) | outdated | indexed |
| `similar` (A 구버전) | 변경 없음 | outdated |

`doc_created_at` NULL인 경우 A를 최신으로 간주.

## 설정값 (settings.yaml)

```yaml
dedup:
  enabled: true
  ngram: 3
  num_bands: 4
  simhash_bits: 64
  hamming_identical_threshold: 3
  hamming_similar_threshold: 10
  lock_ttl: 10
  lock_acquire_timeout: 5
```

## Redis 키 패턴 (탐지 전용)

| 키 | 타입 | 설명 |
|---|---|---|
| `dedup:band:{band_idx}:{band_val}` | Set | doc_id 집합 (LSH 후보 조회용) |
| `dedup:simhash:{doc_id}` | String | 64비트 simhash 정수 |
| `dedup:titlehash:{doc_id}` | String | 제목 SHA-256 해시 |
| `dedup:lock:{band_idx}:{band_val}` | String | SETNX 밴드 락 (race condition 방지) |

## 완료 기준

- [x] "동일" 문서 유입 시 chunk/embed/upsert 실행 없이 dedup_skipped 상태로 종료
- [x] "제목변경" 문서 유입 시:
  - A가 최신: C outdated 전환 + Qdrant payload 갱신 + simhash_bands 삭제 + A indexed
  - A가 구버전: A outdated 기록, C 변경 없음
- [x] 후보 없음 문서는 기존 파이프라인 정상 실행
- [x] `test_dedup_simhash.py`, `test_dedup_verdict.py` 전체 통과

## 의존성

- 없음

## 오픈 이슈

- title_changed 케이스 MinIO 파일 삭제 (grace period 방식) — 별도 US
- 전체 코퍼스 SimHash 백필 스크립트 — 별도 US
- band 키 SCARD 모니터링 임계치 — 운영 데이터 확보 후 결정
- hamming_identical_threshold 기본값 3 → 일반 문서 기준 5 조정 검토
