# US-03 — Small-to-Big Retrieval (document_aware)

## 상태
todo

## 개요

`HierarchicalNodeParser`를 활용한 Small-to-Big 검색 구현.

현재 `document_aware` 전략은 leaf 노드만 반환하고 parent를 버려서
`recursive`와 사실상 동일하게 동작했으므로 제거됨 (2026-06-09).
이 백로그는 계층 구조를 제대로 활용하는 방식으로 재구현하는 작업.

## 배경

- `get_leaf_nodes()`가 파싱 직후 parent를 모두 버렸고, leaf 크기도 `chunk_size // 2`라
  오히려 `recursive`보다 작은 청크로 검색되는 역효과가 있었음.
- parent를 별도 저장소(Redis 등)에 저장하는 방식은 스토리지가 급격히 커지는 문제가 있음.
- parent 노드를 Qdrant에 벡터 없이 저장하면 추가 인프라 없이 해결 가능.

## 설계

### Ingest 구조

```
Document
    |
    v
HierarchicalNodeParser
    |
    +-------------------------------+
    |                               |
    v                               v
leaf 노드 (chunk_size // 2)      parent 노드 (chunk_size * 2)
    |                               |
    | 임베딩 (dense + sparse)        | 임베딩 없음
    v                               v
Qdrant 포인트 (벡터 O)           Qdrant 포인트 (벡터 없음, payload만)
  id: uuid                         id: uuid
  vector:                          vector: (없음)
    dense: [...]                   payload:
    sparse: {indices, values}        node_id: <uuid>
  payload:                           text: "...큰 문맥..."
    parent_node_id: <uuid>  <-----   doc_key: "kb-id::object-key"
    text: "...작은 청크..."            kb_id: "kb-id"
    doc_key: "kb-id::object-key"     doc_source: "doc.pdf"
    kb_id: "kb-id"
    doc_source: "doc.pdf"
```

### Retrieval 구조

```
쿼리: "X는 무엇인가?"
    |
    v
Qdrant 벡터 검색
  (벡터 없는 parent는 검색 대상에서 자동 제외)
    |
    v
검색 결과 [ node_A, node_B, node_C ]
    |
    +-- parent_node_id 있음 → parent_ids 수집
    |
    +-- parent_node_id 없음 → 현재 text 그대로 사용
         (recursive 전략으로 인덱싱된 문서 — 혼재 상태 자연 처리)
    |
    v
client.retrieve(ids=parent_ids)  ← ID 직접 조회 (벡터 연산 없음)
    |
    v
최종 결과: parent text (풍부한 문맥) 또는 leaf text (fallback)
```

### Delete 구조

```
delete_chunks_by_doc(kb_id, doc_source)
    |
    v
Qdrant 필터: doc_key = "kb-id::object-key"
    |
    +-------------------------------+
    |                               |
    v                               v
leaf 포인트 삭제                  parent 포인트 삭제

-> 기존 delete_chunks_by_doc 코드 변경 없이 동작
   (leaf/parent 모두 동일한 doc_key를 가짐)
```

## 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/pipeline/step/chunk.py` | `document_aware` 전략 재추가, 전체 노드 반환 (leaf + parent 구분) |
| `src/pipeline/step/embed.py` | `parent_node_id`가 없는 노드(leaf)만 임베딩 |
| `src/pipeline/step/upsert.py` | leaf → 벡터 포함 저장, parent → payload만 저장 분기 |
| `src/rag/retriever.py` | 검색 후 `parent_node_id` 유무로 parent text 조회 또는 fallback |

## 주의사항

- `is_leaf` 필터 불필요 — parent는 벡터가 없어 벡터 검색 결과에 원천적으로 안 나옴.
- `recursive`로 인덱싱된 기존 문서와 혼재해도 안전 — `parent_node_id` 없으면 leaf text 사용.
- 검색 품질 향상 효과는 쿼리 유형과 청크 크기에 따라 다름 — 구현 후 실측 필요.
- 추가 인프라 없음 — Qdrant는 벡터 없는 포인트를 기본 지원.

## 검토한 대안 및 이슈

### LlamaIndex AutoMergingRetriever 미사용 이유

LlamaIndex는 `AutoMergingRetriever`를 공식 제공하며, `simple_ratio_thresh`(기본 0.5)로
같은 parent의 자식 중 일정 비율 이상 검색되면 자동으로 parent 텍스트로 교체하는 병합 로직을 갖춤.

```python
AutoMergingRetriever(vector_retriever, storage_context, simple_ratio_thresh=0.5)
```

단, `StorageContext`의 docstore 백엔드로 Qdrant를 사용할 수 없음.
LlamaIndex docstore 지원 백엔드: `SimpleDocumentStore`(인메모리), `RedisDocumentStore`, `MongoDocumentStore` 등.
Qdrant는 vector_store로만 지원되며 docstore 역할은 설계상 불가.

`RedisDocumentStore`를 쓰면 `AutoMergingRetriever` 사용이 가능하지만,
Redis에 parent 노드 텍스트를 저장하면 문서 증가에 따라 Redis 메모리가 급격히 커지는 문제가 있음.

### 채택한 방식의 트레이드오프

Qdrant payload-only 저장 방식은 `AutoMergingRetriever`의 `simple_ratio_thresh` 병합 로직 없이
항상 parent 텍스트를 반환함. 조건부 병합이 없다는 차이가 있지만,
추가 인프라 없이 현재 스택 안에서 해결할 수 있는 가장 현실적인 방안.
