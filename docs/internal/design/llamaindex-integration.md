# LlamaIndex 활용 범위

파싱·청킹·임베딩·검색 각 단계에서 LlamaIndex를 어디까지 쓰고, 어디서부터 자체 구현으로
대체했는지 정리한다. Dagster op 구조는 [dagster-internals.md](dagster-internals.md),
검색 런타임 흐름은 [architecture/runtime.md](../architecture/runtime.md) 참조.

---

## 1. 파싱 — SimpleDirectoryReader

```python
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import PDFReader, MarkdownReader, DocxReader

reader = SimpleDirectoryReader(
    input_files=[local_path],
    file_extractor={
        ".pdf":  PDFReader(),
        ".md":   MarkdownReader(),
        ".docx": DocxReader(),
    }
)
documents = reader.load_data()
```

---

## 2. 청킹 — NodeParser

```python
from llama_index.core.node_parser import (
    SentenceSplitter,            # recursive 전략
    SemanticSplitterNodeParser,  # semantic 전략
)

parsers = {
    "recursive": SentenceSplitter(chunk_size=1024, chunk_overlap=128),
    "semantic":  SemanticSplitterNodeParser(buffer_size=1, breakpoint_percentile_threshold=80),
}
```

---

## 3. 임베딩 — LlamaIndex Embedding

```python
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

embeddings = {
    "ollama": OllamaEmbedding(model_name="bge-m3", base_url="http://ollama:11434"),
    "openai": OpenAIEmbedding(model="text-embedding-3-small", api_key=...),
}
```

---

## 4. 검색 — VectorStoreIndex + QdrantVectorStore

```python
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.qdrant import QdrantVectorStore
from rag_api.pipeline import compute_sparse_tf

vector_store = QdrantVectorStore(
    client=qdrant_client,
    collection_name=kb_id,
    enable_hybrid=True,
    sparse_doc_fn=compute_sparse_tf,    # 인덱싱 시 TF sparse 벡터 생성
    sparse_query_fn=compute_sparse_tf,  # 쿼리 시 TF sparse 벡터 생성
    dense_vector_name="dense",
    sparse_vector_name="sparse",
)
index = VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)
retriever = index.as_retriever(
    similarity_top_k=settings.retrieval.top_k,
    vector_store_query_mode="hybrid",
    alpha=settings.retrieval.alpha,
)
```

---

## 5. Sparse 벡터 — 자체 TF 인코더 (`pipeline/utils/sparse.py`)

FastEmbed BM25를 직접 사용하지 않고, 순수 Python으로 구현한 TF 인코더(`compute_sparse_tf`)를
사용한다. 클라이언트는 TF만 계산하고, IDF는 Qdrant 서버가 코퍼스 기반으로 자동 관리한다
(`Modifier.IDF`). `sparse_doc_fn` / `sparse_query_fn`으로 LlamaIndex에 주입하여 인덱싱·검색
양쪽에서 동일하게 동작한다.

---

## 6. 구현 위치

| 구성 요소 | 위치 |
|-----------|------|
| 파싱 (parse_op) | `src/pipeline/step/parse.py` |
| 청킹 (chunk_op) | `src/pipeline/step/chunk.py` |
| 임베딩 (embed_op) | `src/pipeline/step/embed.py` |
| 자체 TF sparse 인코더 | `src/pipeline/utils/sparse.py` |
| 검색 retriever | `src/rag/retriever.py` |
