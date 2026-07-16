# Qdrant Server-Side IDF for Sparse Vectors

## Background

`fastembed.SparseTextEmbedding("Qdrant/bm25")` was removed due to `onnxruntime`
incompatibility on QEMU ARM64 (see [troubleshooting/sigill-sigkill-qemu-arm64.md](troubleshooting/sigill-sigkill-qemu-arm64.md)).

The replacement uses Qdrant's `Modifier.IDF`, where the client stores only TF (term
frequency) as a sparse vector and Qdrant computes IDF at query time from its inverted
index.

## Implementation

### 1. `src/pipeline/step/sparse.py` (new)

Pure Python TF sparse encoder. Uses `zlib.crc32` for deterministic token-to-index
mapping with no external dependencies.

```python
def compute_sparse_tf(texts: List[str]) -> BatchSparseEncoding:
    for text in texts:
        tokens = re.findall(r"\w+", text.lower())
        counts = Counter(tokens)
        indices = [zlib.crc32(t.encode()) & 0x7FFFFFFF for t in counts]
        values = [float(v) for v in counts.values()]
```

### 2. `src/infra/qdrant.py`

Collection creation activates `Modifier.IDF`:

```python
sparse_vectors_config={
    SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
        modifier=qmodels.Modifier.IDF,
    ),
}
```

### 3. `src/rag/retriever.py`

`LlamaIndex QdrantVectorStore` uses custom sparse functions instead of `fastembed_sparse_model`:

```python
QdrantVectorStore(
    ...
    sparse_doc_fn=compute_sparse_tf,
    sparse_query_fn=compute_sparse_tf,
)
```

## How Qdrant IDF Works

### Inverted index storage

Qdrant stores sparse vectors in an inverted index internally. Document frequency (df)
is updated incrementally as documents are added or removed — no full corpus rescan needed.

```
Document A: {apple: 0.3, banana: 0.5}
Document B: {apple: 0.2, cherry: 0.4}
Document C: {banana: 0.1, cherry: 0.6}

[Qdrant internal inverted index]
apple  → {doc_A: 0.3, doc_B: 0.2}   df=2
banana → {doc_A: 0.5, doc_C: 0.1}   df=2
cherry → {doc_B: 0.4, doc_C: 0.6}   df=2
```

### Query-time IDF calculation

```
Query: "apple banana"  →  TF: {apple: 1.0, banana: 1.0}

N = 3 (total documents)
IDF(apple)  = log(N / df) + 1   (df=2, read from inverted index in O(1))
IDF(banana) = log(N / df) + 1

score(doc_A) = TF_query(apple)  * IDF(apple)  * TF_stored(doc_A, apple)
             + TF_query(banana) * IDF(banana) * TF_stored(doc_A, banana)
```

IDF is computed dynamically at query time from the inverted index df values.
The client stores only TF, and BM25 scoring is applied correctly.

## Comparison with FastEmbed BM25

| Item | FastEmbed BM25 | Qdrant Modifier.IDF |
|------|----------------|---------------------|
| IDF calculation point | At indexing (baked into stored vector) | At query time (dynamic from inverted index) |
| IDF corpus basis | Pre-trained general corpus | Actual documents in the collection |
| Effect of adding documents on existing IDF | None (stored vectors are fixed) | Automatically reflected from next query |
| Re-indexing required | No (IDF is fixed) | No (dynamically calculated) |
| External dependency | onnxruntime (SIGILL on QEMU) | None |

## Migration Notes

- Existing Qdrant collections created without `Modifier.IDF` must be recreated.
- Token-to-index mapping changed from fastembed fixed vocabulary to CRC32 hash.
  Existing vectors are incompatible — full re-indexing required.
