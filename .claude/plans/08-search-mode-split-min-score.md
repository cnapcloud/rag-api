# Plan: US-08 검색 모드 분리 및 유사도 기반 필터

## Context

hybrid 검색(RRF)은 순위 기반 스코어라 "유사도 낮은 결과 제거"가 불가능하다.
dense-only 검색 경로(`search_similarity_kb`)를 추가하고 설정 구조를 모드별로 분리한다.
파이프라인 순서: 코사인 score 필터 → rerank (similarity 모드만).

---

## 1. `src/config/settings.py`

새 서브모델 2개 추가 후 `RetrievalSettings` 재편:

```python
from typing import Literal

class HybridSearchSettings(BaseModel):
    alpha: float = 0.5
    merge_strategy: str = "rrf"

class SimilaritySearchSettings(BaseModel):
    min_score: float = 0.0

class RetrievalSettings(BaseModel):
    mode: Literal["hybrid", "similarity"] = "hybrid"
    top_k: int = 10
    hybrid: HybridSearchSettings = Field(default_factory=HybridSearchSettings)
    similarity: SimilaritySearchSettings = Field(default_factory=SimilaritySearchSettings)
    rerank: RerankerSettings = Field(default_factory=RerankerSettings)
```

기존 `alpha`, `merge_strategy` 최상위 필드 제거.

---

## 2. `settings.yaml`

```yaml
retrieval:
  mode: "hybrid"
  top_k: 10
  hybrid:
    alpha: 0.5
    merge_strategy: "rrf"
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

---

## 3. `src/rag/retriever.py`

### 리네임
- `search_kb` → `search_hybrid_kb`
- `_search_kb_async` → `_search_hybrid_kb_async`
- 내부에서 `cfg.alpha` → `cfg.hybrid.alpha` 로 참조 변경

### 신규: `search_similarity_kb`

```python
def search_similarity_kb(
    kb_id: str,
    query: str,
    top_k: int | None = None,
    min_score: float = 0.0,
) -> list[SearchResult]:
    cfg = get_settings().retrieval
    _top_k = top_k or cfg.top_k

    index = _build_index(kb_id)
    retriever = index.as_retriever(
        similarity_top_k=_top_k,
        vector_store_query_mode="default",  # dense-only → cosine score
    )
    nodes = retriever.retrieve(query)

    results = []
    for node in nodes:
        score = float(node.score or 0.0)
        if score < min_score:
            continue
        meta = node.metadata
        results.append(SearchResult(...))
    return results
```

`_search_similarity_kb_async` 비동기 래퍼 동일 패턴으로 추가.

### `hybrid_search` 시그니처 변경

```python
async def hybrid_search(
    query: str,
    kb_ids: list[str],
    top_k: int | None = None,
    alpha: float | None = None,      # hybrid 모드 전용, similarity면 무시
    mode: str = "hybrid",
    min_score: float = 0.0,          # similarity 모드 전용
) -> list[SearchResult]:
```

- `mode="hybrid"` → `_search_hybrid_kb_async` 호출 (alpha 사용)
- `mode="similarity"` → `_search_similarity_kb_async` 호출 (min_score 전달, alpha 무시 + 로그)
- 기존 호출자(`mcp_server/tools/search.py`, `main.py`)는 mode 미전달 → `"hybrid"` 기본값으로 동작 유지

---

## 4. `src/api/routers/search.py`

### SearchOptions 재편

```python
class HybridOptions(BaseModel):
    alpha: float = 0.5
    merge_strategy: str = "rrf"

class SimilarityOptions(BaseModel):
    min_score: float | None = None   # None → settings 기본값

class SearchOptions(BaseModel):
    mode: Literal["hybrid", "similarity"] = "hybrid"
    top_k: int = 10
    hybrid: HybridOptions = Field(default_factory=HybridOptions)
    similarity: SimilarityOptions = Field(default_factory=SimilarityOptions)
    rerank: RerankOptions = Field(default_factory=RerankOptions)
```

기존 최상위 `alpha` 필드 제거.

### SearchMeta 필드 추가

```python
score_threshold: float    # 실제 적용된 min_score (0.0 = 비활성)
```

---

## 5. 변경 없는 파일

- `src/mcp_server/tools/search.py` — `hybrid_search` 호출 시 mode 미전달 → "hybrid" 기본값 유지
- `src/main.py` — 동일
- `src/rag/merger.py`, `src/rag/reranker.py` — 변경 없음

---

## 6. 테스트

- `tests/unit/test_search.py` — `TestSearchSimilarityKb` 4개 신규 (dense-only 모드 확인, min_score 필터, 전체 미만 빈 배열)
- `tests/integration/test_search_api.py` — similarity 모드 테스트, invalid mode 422 테스트 추가

---

## 검증

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v
.venv/bin/ruff check src/
```

결과: 87 passed, 2 skipped
