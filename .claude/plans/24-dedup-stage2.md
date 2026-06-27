# Plan: US-24 Dedup Stage 2 — MinHash + pg_trgm

## 신규 파일

### `src/pipeline/ops/dedup/minhash.py`

Kiwi 형태소 분석 → MinHash 서명 산출 → 밴드 분할 → Postgres 저장/조회.

```python
def compute_minhash(text: str, num_hashes: int = 128) -> list[int]: ...
def split_bands(signature: list[int], num_bands: int = 16) -> list[int]: ...
def save_minhash_bands(doc_id: str, bands: list[int]) -> None: ...
def find_candidates_by_bands(bands: list[int]) -> set[str]: ...
def find_candidates_by_title(title: str, threshold: float) -> set[str]: ...
def compute_jaccard(sig_a: list[int], sig_b: list[int]) -> float: ...
def run_stage2(doc_id: str, text: str, title: str) -> DedupResult: ...
```

### `tests/unit/test_dedup_minhash.py`

- MinHash 서명 길이 128 확인
- 동일 텍스트 Jaccard = 1.0
- 무관 텍스트 Jaccard ≈ 0
- 밴드 분할 16개 확인
- find_candidates_by_bands — mock postgres

---

## 수정 파일

### `src/config/settings.py`

`DedupSettings`에 필드 추가:

```python
class DedupSettings(BaseModel):
    ...
    hamming_similar_threshold: int = 10
    jaccard_threshold: float = 0.65
    title_fuzzy_threshold: float = 0.85
    title_only_min_jaccard_floor: float = 0.25
```

### `settings.yaml`

```yaml
dedup:
  ...
  hamming_similar_threshold: 10
  jaccard_threshold: 0.65
  title_fuzzy_threshold: 0.85
  title_only_min_jaccard_floor: 0.25
```

### `src/infra/postgres.py`

```python
def save_minhash_bands(doc_id: str, band_hashes: list[int]) -> None: ...
def get_minhash_signature(doc_id: str) -> list[int] | None: ...
def find_minhash_candidates(band_hashes: list[int]) -> set[str]: ...
def find_title_candidates(title: str, threshold: float) -> set[str]: ...
def delete_minhash_bands(doc_id: str) -> None: ...
```

### `src/pipeline/ops/dedup/__init__.py`

`run_dedup_pipeline()`에 2단계 연결:

```python
# 1단계에서 후보 없을 때
result = run_stage2(doc_id, text, title)
if result.verdict != "proceed":
    run_verdict(doc_id, result, run_id)
    return DedupOutcome(needs_indexing=result.verdict == "similar" and a_is_newer)
```

### `src/pipeline/ops/dedup/verdict.py`

`handle_similar()` 추가 — `doc_created_at` 기준 신구 판단, C outdated 처리.

### `src/defs/jobs/dedup_job.py`

`minhash_op` 추가 (독립 실행용 Dagster 래퍼).

---

## 알고리즘

```
인제스트 시:
  Kiwi 형태소 분석 → 명사/동사 어간 집합
  → 128개 해시 함수로 각 토큰 해싱 → 최솟값 추출 → MinHash 서명 128개
  → 16밴드 × 8행 분할 → minhash_bands 저장

2단계 비교 시:
  A의 밴드값으로 minhash_bands 조회 → 본문 후보
  pg_trgm으로 documents.source similarity ≥ title_fuzzy_threshold → 제목 후보
  합집합 → Jaccard 근사값(일치 해시 수 / 128) 계산
  3분기 임계값 판정 → similar | proceed
```

---

## 구현 순서

1. `settings.py` + `settings.yaml` — 임계값 필드 추가
2. `postgres.py` — minhash_bands CRUD 추가
3. `minhash.py` — 핵심 로직 구현
4. `test_dedup_minhash.py` — 단위 테스트
5. `verdict.py` — `handle_similar()` 추가
6. `__init__.py` — `run_dedup_pipeline()`에 2단계 연결
7. `dedup_job.py` — `minhash_op` 추가
