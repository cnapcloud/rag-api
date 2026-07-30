# pipeline/steps — Step 작성 규칙

## 핵심 원칙

각 Step 함수는 **순수 함수**여야 한다. Dagster `@op` 래퍼(`defs/ops/`)와 `runner.py` 양쪽에서
재사용되기 때문.
외부 상태 변경(Redis, Qdrant, MinIO 쓰기)은 `meta.py`, `upsert.py`에만 허용.

`meta.py`는 인제스트 파이프라인 마지막 단계(`set_indexed`)만 담당하며, 나머지 상태 전이
(`set_pending`/`set_processing`/`set_failed`/`set_deleting` 등)는 파이프라인 안팎에서
공용으로 쓰이므로 `pipeline/utils/doc_state.py`에서 직접 import한다.

## 파이프라인 계약

```
validate(kb_id, doc_source, etag, file_size) → bool
parse(kb_id, doc_source)                     → list[Document]
chunk(documents, strategy, chunk_size, ...)  → ChunkResult(nodes, parents)
embed(nodes)                                 → list[BaseNode]  # embedding 주입됨
upsert(kb_id, doc_key, nodes, parents)      → UpsertResult
set_indexed(doc_id, upsert_result, ...)     → None
```

`chunk()`는 항상 `ChunkResult`를 반환한다 — `.nodes`(leaf, 임베딩·검색 대상)와
`.parents`(ancestor 목록, `strategy="hierarchical"`가 아니면 빈 리스트)로 구성.
호출부가 `list[BaseNode]`를 기대하던 기존 코드는 `.nodes`로 바꿔야 한다
(docs/internal/design/parent-child-chunking.md §4.3).

## 청킹 전략

- `recursive` (SentenceSplitter): 일반 텍스트
- `semantic` (SemanticSplitterNodeParser): embed_model 필요, API 호출 발생
- `hierarchical` (HierarchicalNodeParser): N-level 계층 청킹, leaf만 임베딩·검색되고 ancestor는
  Postgres `parent_chunks`에 저장돼 검색 시 auto-merge로 병합됨 —
  docs/internal/design/parent-child-chunking.md 참고. `chunk_size`가 이 전략에서는 리스트
  (큰 것 -> 작은 것 순, 마지막이 leaf 크기).

기본값은 `settings.yaml`의 `chunking.strategy`.

## 임베딩

Dense + Sparse를 `asyncio.gather`로 병렬 실행.
`embed_model`은 `build_embed_model()`로 생성 (provider: ollama / openai).
테스트에서는 `mock_embed_model` 픽스처 사용.

## 테스트 패턴

```python
# Step 함수를 직접 호출 — Dagster context 불필요
nodes = chunk(docs, strategy="recursive", chunk_size=128, chunk_overlap=16)
assert len(nodes) > 1
```

연속 텍스트(`"A" * 3000`)는 SentenceSplitter가 분할하지 못함.
반드시 공백이 있는 텍스트(`"word " * N`)를 사용할 것.
