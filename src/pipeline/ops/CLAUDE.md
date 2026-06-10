# pipeline/ops — Op 작성 규칙

## 핵심 원칙

각 Op은 **순수 함수**여야 한다. Dagster `@op` 래퍼와 `runner.py` 양쪽에서 재사용되기 때문.
외부 상태 변경(Redis, Qdrant, MinIO 쓰기)은 `meta.py`, `upsert.py`에만 허용.

## 파이프라인 계약

```
validate(kb_id, object_key, etag, file_size) → bool
parse(kb_id, object_key)                     → list[Document]
chunk(documents, strategy, chunk_size, ...)  → list[BaseNode]
embed(nodes)                                 → list[BaseNode]  # embedding 주입됨
upsert(kb_id, doc_key, nodes)               → UpsertResult
meta(kb_id, doc_key, status, ...)           → None
```

## 청킹 전략

- `recursive` (SentenceSplitter): 일반 텍스트
- `semantic` (SemanticSplitterNodeParser): embed_model 필요, API 호출 발생

기본값은 `settings.yaml`의 `chunking.strategy`.

## 임베딩

Dense + Sparse를 `asyncio.gather`로 병렬 실행.
`embed_model`은 `build_embed_model()`로 생성 (provider: ollama / openai).
테스트에서는 `mock_embed_model` 픽스처 사용.

## 테스트 패턴

```python
# Op 함수를 직접 호출 — Dagster context 불필요
nodes = chunk(docs, strategy="recursive", chunk_size=128, chunk_overlap=16)
assert len(nodes) > 1
```

연속 텍스트(`"A" * 3000`)는 SentenceSplitter가 분할하지 못함.
반드시 공백이 있는 텍스트(`"word " * N`)를 사용할 것.
