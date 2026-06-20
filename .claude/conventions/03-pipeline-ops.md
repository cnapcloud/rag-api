# Pipeline Op 작성 규칙

## 핵심 원칙

각 Op은 **순수 함수**로 유지. Dagster `@op` 래퍼(`dagster_pipeline/ops/`)와 `runner.py` 양쪽에서 재사용됨.

외부 상태 변경(쓰기)은 `meta.py`(Redis)와 `upsert.py`(Qdrant)에만 허용.

## 파이프라인 계약

```python
validate(kb_id, doc_source, etag, file_size=0) → bool
parse(kb_id, doc_source)                        → list[Document]
chunk(documents, strategy, chunk_size, ...)     → list[BaseNode]
embed(nodes)                                    → list[BaseNode]  # embedding 주입됨
upsert(kb_id, doc_key, nodes)                  → UpsertResult
meta(kb_id, doc_key, status, ...)              → None
```

## 청킹 전략

| 전략 | 파서 | 특징 |
|------|------|------|
| `recursive` | SentenceSplitter | 일반 텍스트, 빠름 |
| `semantic` | SemanticSplitterNodeParser | embed_model 필요, API 호출 발생 |
| `document_aware` | HierarchicalNodeParser | leaf 노드만 반환 (`get_leaf_nodes()` 사용) |

기본값: `settings.yaml`의 `chunking.strategy`.

## 임베딩 패턴

Dense + Sparse를 `asyncio.gather`로 병렬 실행.

```python
dense_result, sparse_result = await asyncio.gather(
    embed_dense(nodes),
    embed_sparse(nodes),
)
```

`embed_model`은 `build_embed_model()`로 생성 (provider: ollama / openai).

## 메타데이터 주입

청킹 후 각 노드에 다음 메타데이터가 자동 주입됨:

```python
node.metadata.update({
    "chunk_index": i,
    "total_chunks": len(nodes),
    "chunk_strategy": _strategy,
    "chunk_size": _chunk_size,
    "chunk_overlap": _chunk_overlap,
})
```

## Dagster 래퍼 패턴

```python
# dagster_pipeline/ops/ingest_ops.py
@op(required_resource_keys={"redis", "minio", "qdrant", "embedding"})
def chunk_op(context, nodes):
    return chunk(nodes, ...)  # 내부적으로 pipeline/ops/chunk.py 호출
```

Op 함수 자체는 Dagster 의존성 없이 테스트 가능.
