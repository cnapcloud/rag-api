# US-24: Dedup Stage 2 — MinHash Jaccard + pg_trgm 제목 퍼지 필터링

**상태**: done

> 설계: [dedup.md](../../docs/internal/design/dedup.md) (D-03)

## 목적

1단계(SimHash)에서 후보를 찾지 못한 신규 문서 A에 대해, 형태소 기반 MinHash로 본문 Jaccard 유사도를 추정하고
pg_trgm으로 제목 퍼지 유사도를 확인하여 후보를 선별한다.
전수 비교 없이 밴드 인덱스(MinHash) + GIN 인덱스(pg_trgm)로 후보를 추출한다.

## 범위

- Kiwi 형태소 분석 + MinHash 128개 서명 산출
- MinHash 16밴드 × 8행 분할 → Postgres `minhash_bands` 테이블 저장
- pg_trgm GIN 인덱스(`idx_documents_source_trgm`)를 통한 제목 퍼지 후보 조회
- 본문(MinHash 밴드) + 제목(pg_trgm) 후보 합집합 → 3분기 임계값 판정
- settings.yaml `dedup` 섹션에 2단계 임계값 추가

## 비범위

- 3단계 이후 (청크 단위 임베딩 비교)
- 기존 문서 MinHash 백필 스크립트 (별도 US)

## DB 스키마 (완료)

`minhash_bands` 테이블, `idx_minhash_bands_lookup` 인덱스, `pg_trgm` 확장,
`idx_documents_source_trgm` GIN 인덱스 — `migrations/001_initial_schema.sql`에 포함, docker 적용 완료.

## 임계값

| 변수 | 1+2단계만 | 3단계 추가 시 | 근거 |
|------|-----------|--------------|------|
| `jaccard_threshold` | 0.65 | 0.2 | 최종 판정 vs 필터 역할 차이 |
| `title_fuzzy_threshold` | 0.85 | 0.7 | 오탐 방지 vs 후보 확보 |
| `title_only_min_jaccard_floor` | 0.25 | 0.05 | 제목 유사 경로 본문 요건 |

## Verdict

| 조건 | verdict | to_chunk |
|------|---------|----------|
| Jaccard ≥ jaccard_threshold | `similar` | False |
| Jaccard < jaccard_threshold, 제목유사도 ≥ title_fuzzy_threshold, Jaccard ≥ title_only_min_jaccard_floor | `similar` | False |
| Jaccard < jaccard_threshold, 제목유사도 ≥ title_fuzzy_threshold, Jaccard < title_only_min_jaccard_floor | `proceed` | True |
| 둘 다 미달 | `proceed` | True |

| verdict | C 처리 | A 처리 |
|---------|--------|--------|
| `similar` (A 최신) | outdated | indexed |
| `similar` (A 구버전) | 변경 없음 | outdated |
| `proceed` | — | indexed |

판정 점수(jaccard_score, title_score)는 임계값 튜닝용으로 로그에 기록한다.
`candidate_doc_ids`에는 LSH 사전 후보 전체가 아닌, Jaccard/제목 임계값을 통과한 것만 포함된다.
`duplicate_doc_id`는 통과 후보 중 Jaccard 최고값 1건이며, `run_verdict` 진입 시 전체 후보 목록과 함께 로깅된다.
3단계 구현 시 `similar` verdict를 임베딩 정밀 비교로 라우팅하도록 변경한다.

## 완료 기준

- [x] 명백히 무관한 문서가 후보로 올라오지 않음
- [x] 제목만 우연히 비슷하고 본문이 무관한 문서(Jaccard < title_only_min_jaccard_floor)가 proceed 처리됨
- [x] 전수 조사 없이 밴드 인덱스 조회만으로 후보 추출됨을 확인
- [x] `test_dedup_minhash.py` 전체 통과

## 의존성

- US-23 — SimHash 1단계에서 후보를 못 찾은 문서만 2단계로 넘어옴 (dedup.md D-03이 D-01에 의존)

## 오픈 이슈

- 기존 문서 전체 MinHash 백필 스크립트 — 별도 US
- 3단계 구현 시 임계값을 "3단계 추가 시" 값으로 교체
- **(운영 후)** 임계값 운영 데이터 기반 튜닝
- **(운영 후)** 임계값 튜닝용 라벨 데이터셋 점진 구축 (목표 50~100쌍)
