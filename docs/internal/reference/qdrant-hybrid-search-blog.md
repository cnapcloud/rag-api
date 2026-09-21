# Qdrant 하이브리드 검색 설계: RAG 검색 파이프라인의 레이어와 결합 전략

*2026-09-20*

사내 지식을 저장하고 검색하는 RAG 파이프라인, rag-api를 만들면서 가장 많이 다시 그려본 부분은 다름 아닌 검색이었다. 처음에는 단순했다 — 문서를 청킹해 임베딩하고 벡터 DB에 넣은 뒤, 질문을 임베딩해 유사한 청크를 가져오면 된다고 생각했다. 하지만 실제 사내 문서로 검색을 붙여보니 이 방식만으로는 부족했다. 제품 코드나 에러 코드처럼 의미보다 정확한 문자열이 중요한 질의가 있었고, 반대로 표현이 달라도 같은 의미를 찾아야 하는 질의도 있었다. 여러 KB를 동시에 검색하면 KB별 결과를 다시 합쳐야 했고, 순위만으로는 놓치는 관련도를 다시 채점할 리랭킹도 필요했고, 같은 질문이 반복될 때마다 이 과정을 처음부터 다시 치르는 것도 낭비였다.

결국 검색은 다음과 같이 여러 단계의 문제로 나뉘었고, 이 글은 각 단계를 어느 레이어에 맡겼는지를 정리한 기록이다.

```
사용자 쿼리
     │
     ▼
검색 응답 캐시(Redis, 8장) ── hit ──► 응답
     │
    miss
     │
     ▼
KB별 hybrid retrieval — dense+sparse 결합(4장)
     │
     ▼
Parent-Child auto-merge(5장)
     │
     ▼
Multi-KB RRF(4.3장)
     │
     ▼
Rerank(6장)
     │
     ▼
응답
```

중요한 건 이 단계들을 하나의 컴포넌트에 몰아넣지 않았다는 점이다. dense+sparse 결합은 Qdrant와 LlamaIndex에, parent-child 복원과 여러 KB 결과 병합은 Postgres를 오가는 애플리케이션 코드에, 반복 검색 비용 절감은 Redis 캐시 레이어에 맡겼다. 이 글에서 정말 다루고 싶은 것도 "Qdrant hybrid search를 어떻게 호출하는가" 하나가 아니라, 이 경계를 어디에 그었는가다.

- 코드 리파지토리: [github.com/cnapcloud/rag-api](https://github.com/cnapcloud/rag-api)
- 가이드 문서: [rag-docs.cnapcloud.com](https://rag-docs.cnapcloud.com)
- 데모: [rag-admin.cnapcloud.com](https://rag-admin.cnapcloud.com), [chat.cnapcloud.com](https://chat.cnapcloud.com) (guest/guest, 09:00~18:00 KST 운영)

이 구조를 만들기 전에 먼저 벡터 스토어를 골라야 했다. 벡터 스토어는 임베딩을 저장하고 유사도로 검색해주는 저장소다. 말은 간단하지만 막상 고르려고 보면 성격이 꽤 다른 제품들이 늘어서 있다. pgvector는 "이미 쓰던 Postgres에 벡터 컬럼 하나 더 얹는다"는 실용적인 접근이고, Milvus는 처음부터 수억 단위 벡터를 분산 처리하려고 태어난 물건이고, Weaviate는 벡터화 모듈까지 끌어안은 올인원에 가깝다. Qdrant, Weaviate, Milvus, pgvector를 두고 저울질하다가, 결국 이 프로젝트가 정말로 필요로 하는 게 뭔지를 세 가지 조건으로 좁혔다.

첫 번째는 검색 품질이었다. dense 벡터만으로는 제품 코드나 에러 코드처럼 정확한 문자열을 찾아야 하는 순간에 자주 삐끗한다. dense와 sparse(BM25)를 함께 운영할 수 있어야 위 다이어그램의 첫 단계(KB별 hybrid retrieval)가 성립한다. 두 번째는 운영이었다. 이미 MinIO·Redis·Postgres로 셀프호스팅 스택을 꾸려둔 상태에서, 새 벡터 DB 하나 때문에 운영 부담이 눈에 띄게 늘어나는 건 피하고 싶었다. 세 번째는 결합 로직을 애플리케이션이 떠안는 범위였다. dense와 sparse 결과를 각각 호출하고 정규화해 합치는 코드를 전부 직접 짜는 것도 가능하지만, 그러면 벡터 스토어를 고른 의미가 줄어든다 — 벡터 DB가 대신해줄 수 있는 부분은 최대한 맡기고 싶었다.

이 기준에서 pgvector는 첫 번째 조건에서, Milvus는 두 번째 조건(etcd·별도 오브젝트 스토리지까지 딸려온다)에서 먼저 밀렸다. Weaviate는 하이브리드를 네이티브로 지원하지만 벡터화 모듈 같은 무게가 함께 붙는다. 세 조건을 모두 통과한 건 Qdrant뿐이었다 — Apache 2.0 오픈소스에, 컨테이너 하나로 가볍게 뜨면서 하나의 point에 dense·sparse named vector를 같이 담아 하이브리드 조회를 컬렉션 레벨에서 그대로 지원한다. 그래서 이 프로젝트는 Qdrant를 택했다.

## 1. 들어가며 — Qdrant는 파이프라인 어디에서 쓰이는가

이 글은 인제스트 파이프라인 전체가 아니라 Qdrant를 중심에 둔 검색 레이어에 집중한다. RAG 파이프라인 안에서 Qdrant가 실제로 맞물리는 지점은 두 곳뿐이다 — 문서를 인제스트할 때(쓰기)와 검색 쿼리가 들어올 때(읽기).

Qdrant를 채우는 흐름(인제스트, 쓰기)과 Qdrant를 조회하는 흐름(검색, 읽기)은 별개의 경로다. 둘을 하나의 화살표로 뭉쳐 그리면 "누가 Qdrant에 쓰고 누가 읽는지"가 흐려지므로 나눠서 그린다.

**인제스트(쓰기) 경로 — Dagster가 주도**
```
인제스트 요청 (업로드/커넥터 동기화)
     │
     ▼
FastAPI가 원본 파일을 MinIO에 저장  ← upload_object()
     │
     ▼
Redis(queue:upload)  ← enqueue_upload_event()가 push
     │
     ▼
Dagster (event_queue_sensor가 큐를 poll해 ingest_job 트리거)
     │
     ▼
MinIO에서 원본 파일 재조회  ← Dagster가 파싱을 위해 읽어옴
     │
     ▼
Dagster (파싱 · 청킹 · 임베딩)
     │
     ├─ 메타데이터 저장 ──────► Postgres (KB/문서 정보)
     │
     └─ dense + sparse 벡터 upsert ──► Qdrant
```

**검색(읽기) 경로 — FastAPI가 주도**
```
사용자 쿼리
     │
     ▼
FastAPI (검색 API)
     │
     ▼
검색 캐시(Redis) 조회 ── hit ──► 응답
     │
    miss
     │
     ▼
Qdrant (dense+sparse hybrid 조회)
     │
     ▼
Rerank API(jina | internal) (or RRF fallback)
     │
     ├─ 캐시 저장 ──► Redis
     │
     ▼
응답
```

두 경로는 Qdrant라는 저장소만 공유할 뿐, 호출 시점과 주체가 완전히 다르다 — 인제스트는 문서 업로드 시 Dagster 파이프라인이 비동기로 실행하고, 검색은 사용자 요청이 올 때마다 FastAPI가 동기로 실행한다.

읽기 경로에서 Qdrant가 하는 일이 바로 이 dense+sparse 결합이다. dense만으로는 고유명사·코드 식별자 같은 정확 매칭에 약하고, sparse만으로는 의미 유사도를 못 잡는데, 이 둘을 애플리케이션 코드에서 직접 합치지 않고 Qdrant(및 아래 4장에서 다룰 LlamaIndex 위임)에 맡길 수 있다는 점이 이 파이프라인이 하이브리드 검색을 구현한 방식이다.

이어지는 장에서는 이 두 경로가 지나는 각 레이어를 실제 코드와 함께 순서대로 살펴본다.

| 레이어 | 담당하는 문제 | 장 |
|---|---|---|
| Qdrant | dense/sparse 벡터 저장(컬렉션·point 스키마) 및 upsert | 2, 3 |
| Qdrant + LlamaIndex | KB 내부 hybrid 결합(dense+sparse) | 4 |
| 애플리케이션 코드 + Postgres | 여러 KB 결과의 RRF 병합, parent-child auto-merge | 4.3, 5 |
| Rerank API | 후보 재채점(jina / internal, RRF fallback) | 6 |
| Dagster + Qdrant | 문서 삭제 정합성 | 7 |
| Redis | 검색 응답 캐시 | 8 |
| Qdrant | 저장 공간·인덱스 파라미터 트레이드오프 | 9 |

## 2. Collection 설계 — Point 스키마

Qdrant의 point 하나가 dense·sparse 벡터와 payload를 어떻게 함께 담는지부터 본다. payload는 nested 구조 없이 전부 top-level 필드로 flatten되어 있다.

```
Point
├── id        : uuid4
├── vector
│   ├── "dense"  (size=1024, distance=COSINE) — bge-m3 (ollama 기본)
│   └── "sparse" (indices/values, modifier=IDF) — BM25
└── payload   (nested 없이 top-level로 flatten)
```

payload에는 20개 가까운 필드가 들어가지만, 검색·삭제 때 실제로 filter 조건으로 쓰이는 필드는 다음과 같다.

| 필드 | 타입 | 용도 |
|---|---|---|
| `doc_id` | str | 삭제·payload 업데이트 시 filter 키(`FieldCondition`) |
| `text` | str | 검색 결과로 바로 노출되는 본문 |

`kb_id`는 payload에도 저장되지만 filter 키가 아니라 collection 이름 그 자체다 — KB마다 별도 collection이라 payload에서 다시 걸러낼 필요가 없다. `chunk_index`도 실제로 filter 조건에 쓰이는 코드는 없고, 청크 순서를 식별하는 메타데이터다. 이 외에 `title`, `source`, `page_num`, `embedding_model`, `chunk_strategy`, `updated_at` 등이 함께 저장되지만, 필터보다는 사용자에게 문서 정보를 정확히 보여주는 메타데이터로 쓰인다 — 추후 필요해지면 이 필드들도 검색 filter 조건으로 추가할 수 있다. 전체 필드 목록은 [`src/rag_api/pipeline/steps/upsert.py:60-81`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/pipeline/steps/upsert.py#L60-L81)을 참조한다.

```python
c = client or get_qdrant_client()
vector_size = get_settings().embedding.vector_size
...
c.create_collection(
    collection_name=kb_id,
    vectors_config={
        DENSE_VECTOR_NAME: qmodels.VectorParams(
            size=vector_size, distance=qmodels.Distance.COSINE,
        ),
    },
    sparse_vectors_config={
        SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
            modifier=qmodels.Modifier.IDF,
        ),
    },
)
```
*([`src/rag_api/infra/qdrant.py:61-97`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/infra/qdrant.py#L61-L97), client·vector_size 초기화 후 collection 생성)*

## 3. Dense + Sparse 동시 저장 (Upsert)

서로 다른 시점, 다른 라이브러리에서 만들어진 두 벡터가 upsert 단계에서 하나의 point로 합쳐지는 과정을 다룬다.

```
청크 텍스트 ─► dense vector ─┐
             └► sparse vector ┴──► 같은 PointStruct
```

```python
import uuid
from qdrant_client.http import models as qmodels
from rag_api.infra import qdrant as qdrant_infra

points: list[qmodels.PointStruct] = []
for en in embedded_nodes:
    node = en.node
    meta = node.metadata
    ...
    points.append(
        qmodels.PointStruct(
            id=str(uuid.uuid4()),
            vector={
                qdrant_infra.DENSE_VECTOR_NAME: en.dense_vector,
                qdrant_infra.SPARSE_VECTOR_NAME: qmodels.SparseVector(
                    indices=en.sparse_indices,
                    values=en.sparse_values,
                ),
            },
            payload=payload,
        )
    )

if points:
    c = client or get_qdrant_client()
    c.upsert(collection_name=kb_id, points=points)  # qdrant-client 라이브러리의 API 그대로 호출
```
*([`src/rag_api/pipeline/steps/upsert.py:1-98`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/pipeline/steps/upsert.py#L1-L98), point 생성 후 Qdrant에 upsert)*

`payload`에 실제로 들어가는 값은 대략 이런 모습이다 (2장에서 본 필드 목록의 예시):

```python
payload = {
    "kb_id": "kb_a1b2c3",
    "doc_id": "doc_9f8e7d",
    "chunk_index": 3,
    "text": "Qdrant는 dense와 sparse 벡터를 하나의 컬렉션에서...",
    "title": "2026 하이브리드 검색 가이드.pdf",
    "embedding_model": "bge-m3",
    ...  # source, doc_type, chunk_strategy, updated_at 등 메타데이터 필드
}
```
*([`src/rag_api/pipeline/steps/upsert.py:60-81`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/pipeline/steps/upsert.py#L60-L81), 실제 필드 구성 예시)*

## 4. 하이브리드 쿼리 — 결합은 두 단계로 나뉜다

결합(fusion)은 한 곳에서 일어나지 않는다. 하나의 KB(=Qdrant collection) 안에서 dense와 sparse를 합칠 때와, 여러 KB를 동시에 검색해 그 결과를 다시 합칠 때는 풀어야 하는 문제 자체가 다르기 때문이다. 같은 collection 안의 dense·sparse 점수는 정규화만 하면 바로 비교할 수 있지만, 서로 다른 KB에서 나온 결과는 collection마다 벡터 분포도 다르고 이미 한 번 결합을 거친 값이라 원점수를 그대로 비교할 수 없다 — 그래서 원점수 대신 "몇 등이었는가(rank)"만 보는 방식이 필요해진다. 이 프로젝트는 전자를 LlamaIndex의 Relative Score Fusion에, 후자를 자체 구현한 RRF(Reciprocal Rank Fusion)에 맡기는 2단 구조로 이 문제를 풀었다.

여기서 LangChain 대신 LlamaIndex를 쓴 이유도 짚고 넘어갈 만하다. LangChain은 에이전트·멀티스텝 체인처럼 범용 LLM 오케스트레이션에 강점이 있는 범용 툴킷에 가깝고, LlamaIndex는 처음부터 RAG(데이터 인덱싱·검색)에 초점을 맞춰 만들어졌다. dense+sparse 점수를 정규화해 가중합하는 계산 자체(4.2 참고)는 복잡하지 않지만, `QdrantVectorStore(enable_hybrid=True)`처럼 sparse 임베딩 함수 연결·쿼리 실행까지 한 번에 묶어주는 벡터 DB 통합이 이미 갖춰져 있다는 점에서 LangChain보다 붙이기 쉬웠다. (hierarchical chunking을 쓸 때 leaf 검색 결과를 부모 청크로 되돌리는 auto-merge는 이 LlamaIndex 통합의 범위 밖이다 — 5장에서 따로 다룬다.)

```
쿼리
  │
  ▼
[KB 1] QdrantVectorStore(enable_hybrid=True)  ← 1단계: dense+sparse 결합 (Relative Score Fusion)
[KB 2] QdrantVectorStore(enable_hybrid=True)  ← 동일하게 KB별로 독립 수행
  │
  ▼
KB별 결과 리스트
  │
  ▼
rrf_merge()  ← 2단계: 서로 다른 KB의 결과를 rank 기준으로 재결합 (RRF)
  │
  ▼
최종 정렬 결과
```

### 4.1 검색 모드 — dense-only vs hybrid

검색 API는 매 쿼리마다 하이브리드를 쓰는 게 아니라 `mode` 파라미터로 두 경로 중 하나를 고른다. `mode="similarity"`면 `vector_store_query_mode="default"`로 dense 벡터만 쓰고, 그 외에는 `"hybrid"`로 dense+sparse를 함께 쓴다.

`_build_index(kb_id)` 내부에서 Qdrant client가 `QdrantVectorStore`를 거쳐 `index`까지 연결되는 경로는 이렇다.
```
client = get_qdrant_client()
       │
       ▼
qdrant_vector_store = QdrantVectorStore(client=client, collection_name=kb_id)
       │
       ▼
index = VectorStoreIndex.from_vector_store(qdrant_vector_store)
       │
       ▼
index.as_retriever(...)  ← 쿼리 시점에 이 retriever가 client를 통해 Qdrant에 실제 요청
```

이 `index`를 받아 `mode`에 따라 dense-only 또는 hybrid retriever를 만드는 부분이 아래 코드다.

```python
index = _build_index(kb_id)  # kb_id의 collection을 감싼 LlamaIndex VectorStoreIndex

if mode == "similarity":
    retriever = index.as_retriever(
        similarity_top_k=top_k,
        vector_store_query_mode="default",
    )
else:
    retriever = index.as_retriever(
        similarity_top_k=top_k,
        vector_store_query_mode="hybrid",
        alpha=alpha,
    )
```
*([`src/rag_api/query/retriever.py:209-220`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/query/retriever.py#L209-L220), mode에 따라 dense-only/hybrid retriever 생성)*

이렇게 만든 `retriever`로 이어서 `retriever.retrieve(retrieve_input)`을 호출해 실제 검색을 수행한다(같은 함수의 뒷부분, `retriever.py:222-229`).

### 4.2 KB 내부 결합 — Relative Score Fusion

이 결합은 KB 하나(=collection 하나)의 쿼리 결과 안에서만 일어난다. `enable_hybrid=True`로 만든 `QdrantVectorStore`가 그 KB에 하이브리드 쿼리를 보내면, 같은 KB 안에서 나온 dense 결과와 sparse 결과 각각의 점수를 0~1로 min-max 정규화한 뒤 `alpha`로 가중합해 그 KB의 결과 리스트 하나를 만든다 — `fused_score = alpha * dense_score + (1 - alpha) * sparse_score` (`settings.yaml`의 `alpha` 기본값은 0.5, dense/sparse 동등 가중치). 이건 RRF가 아니라 **Relative Score Fusion**이라고 부르는 별개의 방식이다 — 순위가 아니라 정규화된 점수 자체를 합산한다는 점이 RRF와 다르다. KB가 여러 개면 이 과정 자체가 KB마다 독립적으로 반복되고, 그렇게 나온 KB별 결과 리스트를 다시 합치는 건 4.3의 몫이다.

```python
vector_store = QdrantVectorStore(
    client=client, collection_name=kb_id,
    enable_hybrid=True,
    sparse_doc_fn=compute_sparse_tf, sparse_query_fn=compute_sparse_tf,
    dense_vector_name="dense", sparse_vector_name="sparse",
)
```
*([`src/rag_api/query/retriever.py:39-54`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/query/retriever.py#L39-L54), QdrantVectorStore로 hybrid 벡터 스토어 구성)*

### 4.3 복수 KB 결합 — RRF

여러 KB를 한 번에 검색하는 경우에는 KB마다 이미 위 4.2 과정을 거쳐 나온 결과 리스트가 여러 개 생긴다. 이 리스트들은 서로 다른 collection에서 나왔기 때문에 점수 스케일이 다를 수 있어, 점수 대신 각 리스트 안에서의 순위(rank)만 이용해 다시 합친다. 청크마다 `1 / (k + rank)`를 모든 리스트에 걸쳐 더한 값이 최종 점수가 되고, 등수가 높을수록(1등, 2등...) 기여도가 커진다.

```python
def rrf_merge(result_lists: list[list[QueryResult]], k: int = 60):
    scores: dict[str, float] = {}
    for results in result_lists:
        for rank, result in enumerate(results, start=1):
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (k + rank)
    ...
```
*([`src/rag_api/query/merger.py:8-20`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/query/merger.py#L8-L20), 멀티 KB 병합)*

## 5. Parent-Child 구조 — Qdrant는 leaf만 담는다

hierarchical chunking(`chunking.strategy="hierarchical"`)을 쓰면 한 문서가 여러 크기 레벨로 계층적으로 쪼개진다 — 상위로 갈수록 큰 블록, 맨 아래(leaf)가 가장 작은 조각이다. 이때 Qdrant에 올라가는 건 leaf 노드뿐이다. 상위(ancestor) 노드는 애초에 임베딩되지도, Qdrant에 저장되지도 않는다 — dense/sparse 검색 대상은 항상 leaf 레벨로 한정하고, 상위 블록은 Postgres의 `parent_chunks` 테이블에 텍스트 그대로 보관해둔다.

예를 들어 `chunk_size=[2048, 512]`(2레벨, `settings.yaml`의 예시값)로 15,000자짜리 문서 하나를 청킹하면 이렇게 된다.

```
15,000자 문서
   │
   ├─ level 0 (root, 최대 2048자) → 대략 8개 블록 (P1..P8)     ─┐
   │                                                        ├─ Postgres parent_chunks
   └─ level 1 (leaf, 최대 512자)  → 대략 30개 블록 (L1..L30)   ─┘  (root는 임베딩/검색 대상 아님)
        │
        각 Lx는 자신이 속한 Px를 parent_chunk_id로 가짐
        (예: L1~L4는 P1 소속 — 512자씩 4개 정도면 2048자 블록 하나를 채운다)
        │
        └─ leaf(L1..L30)만 dense+sparse 임베딩 ──► Qdrant
```

`SentenceSplitter`는 문장 경계를 지키며 자르기 때문에 `chunk_size`는 정확한 길이가 아니라 상한선이다 — 실제 블록 길이와 개수는 문장이 끊기는 위치에 따라 이 숫자보다 들쭉날쭉하다.

레벨이 2개(root/leaf)뿐이라 여기서는 "mid" 레벨이 없지만, `chunk_size`에 값을 3개 이상 주면(예: `[4096, 1024, 256]`) root와 leaf 사이에 mid 레벨이 하나 이상 더 생긴다 — 구조는 아래 다이어그램처럼 N레벨로 일반화된다.

```
Document
   │  HierarchicalNodeParser (LlamaIndex)
   ▼
level 0 (root, largest block)    ─┐
level 1..N-2 (mid)                ├─ all in Postgres parent_chunks (not embedded, not in Qdrant)
level N-1 (leaf, smallest block) ─┘                   │
   │                                                  │
   └─ leaf only, dense+sparse embed ──► Qdrant (payload.parent_chunk_id references direct parent)
```

각 leaf 노드의 payload에는 자신의 바로 위 부모 id가 `parent_chunk_id`로 함께 저장된다.

```python
for n in leaves:
    n.metadata.update({
        "chunk_strategy": "hierarchical",
        "chunk_size": _chunk_size,
        "chunk_overlap": _chunk_overlap,
        "parent_chunk_id": _related_id(n.relationships.get(NodeRelationship.PARENT)),  # leaf 자신이 아니라 바로 위 부모의 id
    })
```
*([`src/rag_api/pipeline/steps/chunk.py:262-269`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/pipeline/steps/chunk.py#L262-L269), leaf 노드 payload에 부모 id 기록)*

인제스트 시에는 Postgres에 부모 행을 먼저 저장한 뒤에 Qdrant에 leaf를 upsert한다 — leaf의 `parent_chunk_id`가 검색 시점에 항상 이미 존재하는 부모를 가리키도록 순서를 맞춘 것이다.

```python
delete_parent_chunks_by_doc(doc_id)                          # Postgres: 이 문서의 옛 부모 청크 삭제
save_parent_chunks(doc_id, kb_id, parents or [])             # Postgres: 새 부모 청크 저장
...
qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id, client)  # Qdrant: 이 문서의 옛 leaf 청크 삭제
...
qdrant_infra.upsert_chunks(kb_id, points, client)            # Qdrant: 새 leaf 청크(points) upsert
```
*([`src/rag_api/pipeline/steps/upsert.py:42-98`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/pipeline/steps/upsert.py#L42-L98), Postgres 부모 저장 후 Qdrant leaf 삭제·upsert)*

### 5.1 검색 결과 병합(auto-merge) — Qdrant 바깥에서

Qdrant는 leaf 단위로만 검색하기 때문에 결과도 원래는 leaf 조각으로 흩어져 나온다. 같은 부모 아래에서 leaf가 여러 개 함께 뽑히면 조각난 텍스트를 그대로 보여주는 대신 부모의 전체 텍스트로 되돌려서(auto-merge) 보여주는 쪽이 낫다 — 이건 LlamaIndex의 auto-merging retriever 기능을 가져다 쓴 게 아니라, leaf 검색 결과를 `parent_chunk_id`로 그룹핑하고 Postgres에서 부모 행을 조회해 직접 병합하는 `_auto_merge_parents`라는 이 프로젝트의 자체 구현이다.

```python
ids = {r.parent_chunk_id for r in active if r.parent_chunk_id}
ancestors = get_parent_chunks(list(ids))
...
for pid, children in groups.items():
    a = ancestors[pid]
    if len(children) / a["child_count"] >= threshold:
        r = _build_merged_result(a, children)
        ...
```
*([`src/rag_api/query/retriever.py:161-186`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/query/retriever.py#L161-L186), 부모 id로 그룹핑 후 threshold 이상이면 부모 텍스트로 교체)*

병합 여부는 "그 부모의 자식 leaf 중 몇 개가 이번 검색 결과에 함께 걸렸는가"의 비율(`threshold`)로 정한다 — 예를 들어 한 부모 아래 leaf 4개 중 3개가 상위 결과에 함께 걸렸으면 조각을 그대로 두지 않고 부모 전체 텍스트 하나로 합쳐서 반환한다.

```
parent P (child_count=4)
├── leaf A  ← 검색 결과에 포함
├── leaf B  ← 검색 결과에 포함
├── leaf C  ← 검색 결과에 포함
└── leaf D  (미포함)

children/child_count = 3/4 = 0.75 ≥ threshold(예: 0.6)
   ⇒ A, B, C 세 조각을 버리고 P의 전체 텍스트 하나로 교체해 반환
```

이 판정은 한 레벨에서 끝나지 않는다 — 병합된 결과를 다시 그 위 레벨과 비교해 `max_depth`(계층 레벨 수 - 1)까지 반복하므로, root까지 겹겹이 쌓인 계층에서는 여러 단계를 한 번에 접어올릴 수도 있다. 이 병합은 이 파이프라인 안에서 KB별 검색(4.2) 직후, 여러 KB를 RRF로 합치기(4.3) 전에 KB마다 독립적으로 일어난다.

이 구조에서 Qdrant는 leaf 벡터 검색까지만 책임지고, "leaf 여러 개를 부모 하나로 되돌릴지"는 이 프로젝트가 검색 이후 단계에서 Postgres를 오가며 직접 판단한다 — 4장의 KB 내부/KB 간 결합과 마찬가지로, Qdrant가 모르는 문제(계층 구조)는 Qdrant 바깥에서 풀었다.

LlamaIndex에도 같은 목적의 `AutoMergingRetriever`가 있지만 이 프로젝트는 가져다 쓰지 않았다. `AutoMergingRetriever`는 leaf·ancestor 노드 전체가 살아있는 docstore(노드 그래프, `node.relationships` 포함)를 전제로 동작하는데, Qdrant에는 커스텀 flat payload만 올라가고 LlamaIndex 표준 노드 직렬화를 쓰지 않아 검색 시점엔 그 `relationships`가 이미 사라진 상태다. 인제스트 시점에 남겨둔 건 `parent_chunk_id` 문자열 하나뿐이라, `AutoMergingRetriever`를 쓰려면 wrapper retriever에 더해 완전한 노드 그래프를 다시 들고 있는 docstore를 별도로 유지해야 했다 — 그 비용이 `parent_chunk_id` 체인만 따라가는 재귀 함수 하나보다 오히려 크다고 판단해 자체 구현을 택했다.

## 6. 리랭킹 — Qdrant 이후 경계

Qdrant가 dense+sparse로 뽑아주는 점수는 쿼리와 문서를 각각 따로 임베딩해 비교하는 bi-encoder 방식이라, 계산은 빠르지만 둘 사이의 미묘한 관계(문맥상 진짜 관련 있는지)까지는 못 본다. 여기에 반해 rerank는 쿼리와 문서를 한 쌍으로 묶어 모델에 같이 넣고 관련도를 다시 채점하는 cross-encoder 방식이라 정확도는 훨씬 높지만, 후보 전체에 매번 이 방식을 적용하면 느리다. 그래서 이 프로젝트는 Qdrant(+RRF)로 빠르게 더 큰 후보 집합(`top_k`)을 추려낸 다음, 그 후보에 대해서만 rerank API를 불러 관련도를 다시 채점하고 최종적으로 보여줄 더 적은 개수(`top_n`)로 줄이면서 재정렬하는 2단계 구조를 쓴다 — rerank가 순위만 바꾸는 게 아니라 개수도 함께 줄이는 이유다.

`retrieval.rerank.provider` 설정값이 `jina`(Jina Rerank API)와 `internal`(Cohere 호환 스키마를 쓰는 자체 호스팅 리랭크 서버) 두 가지를 지원한다 — 둘 다 요청/응답 스키마가 같아서 `_rerank_http` 하나가 URL만 바꿔가며 공용으로 처리한다.

```
결과(top_k) ─► rerank API(jina | internal) 성공 ─► top_n개로 재정렬
            └► 실패 ─► fallback(RRF score 기준 top_n개)
```

```python
try:
    reranked = await _rerank_http(
        url=url, query=query, results=results, top_n=_top_n,
        api_key=cfg.api_key, model=cfg.model, timeout_sec=cfg.timeout_sec,
    )
    return reranked, cfg.provider, False
except Exception as e:
    logger.warning("Reranker failed (provider=%s), applying fallback: %s", cfg.provider, e)
    if cfg.fallback_on_error:
        return _fallback(results, _top_n), cfg.provider, True
    raise
```
*([`src/rag_api/query/reranker.py:72-111`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/query/reranker.py#L72-L111), rerank 시도 후 실패 시 fallback)*

## 7. 문서 삭제 정합성

문서 삭제 요청이 Redis 큐를 거쳐 Qdrant의 filter 기반 delete로 반영되는 흐름과, 상태별로 실패를 다르게 처리하는 방식을 다룬다.

```
Redis(queue:delete) ─► Dagster op(delete_op) ─► Qdrant filter delete
```

```python
def delete_chunks_by_doc_id(kb_id: str, doc_id: str, client=None) -> None:
    c = client or get_qdrant_client()
    c.delete(
        collection_name=kb_id,
        points_selector=qmodels.FilterSelector(
            filter=qmodels.Filter(
                must=[qmodels.FieldCondition(
                    key="doc_id", match=qmodels.MatchValue(value=doc_id),
                )]
            )
        ),
    )
```
*([`src/rag_api/infra/qdrant.py:114-133`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/infra/qdrant.py#L114-L133), doc_id filter로 chunk 삭제)*

이 `delete_chunks_by_doc_id`를 호출하는 쪽에서는 삭제 호출 자체는 상태와 무관하게 동일하고, 그 실패를 다루는 방식만 다르다. `delete_doc`은 이 호출(Qdrant 삭제) 다음에 Postgres 상태를 바꾸는 `_delete_db_record`를 실행한다 — `status == "indexed"`였던 문서는 row를 지우지 않고 `status`만 `'deleted'`로 바꾸는 soft-delete를 탄다. 이때 Qdrant 삭제가 실패한 채로 넘어가면 Postgres는 `'deleted'`인데 Qdrant엔 청크가 그대로 남아 검색되는 불일치가 생긴다. 그래서 `indexed` 상태에서는 예외를 삼키지 않고 그대로 전파해 뒤의 `_delete_db_record` 실행 자체를 막는다 — Postgres `status`도 Qdrant 청크도 삭제 전 그대로 남아, 기록과 실물이 어긋나느니 둘 다 안 바뀐 상태를 유지하는 쪽을 택했다. 그 외 상태는 hard-delete(row·S3 CASCADE 삭제)라 이런 불일치가 생기지 않으므로 실패를 삼키고 best-effort로 진행한다.

```python
def _delete_qdrant_chunks(kb_id: str, doc_id: str, status: str) -> None:
    if status == "indexed":
        qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id)
    else:
        try:
            qdrant_infra.delete_chunks_by_doc_id(kb_id, doc_id)
        except Exception as e:
            logger.warning("Qdrant chunk deletion failed (ignored): doc_id=%s err=%s", doc_id, e)
```
*([`src/rag_api/pipeline/steps/delete.py:10-21`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/pipeline/steps/delete.py#L10-L21), 상태에 따라 실패 전파/swallow 분기)*

## 8. 검색 응답 캐시

Qdrant에서 dense+sparse를 조회하고 rerank까지 거치는 비용은 매 쿼리마다 다시 치르기엔 크고, 특히 같은 질문이 반복되는 FAQ성 검색에서는 그 비용이 고스란히 중복된다. 이 프로젝트는 Redis에 검색 응답 자체를 캐싱해 이 중복을 없앴다.

캐시 판정 방식은 `cache.match_mode` 설정으로 둘 중 하나만 켜진다. 질의 문자열이 정확히 같은지만 보는 `"exact"`(기본값)와, 질의 임베딩을 코사인 유사도로 비교해 살짝 다르게 표현된 질문까지 맞히는 `"semantic"` 중에서 고를 수 있다.

```python
cached, query_embedding = search_cache.lookup(
    req.query, req.kb_ids, effective_options, cache_cfg,
)
if cached is not None:
    cached["meta"]["cache_status"] = "hit"
    return SearchResponse(**cached)
```
*([`src/rag_api/api/routers/search.py:129-134`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/api/routers/search.py#L129-L134), 캐시 hit 시 Qdrant/rerank를 거치지 않고 즉시 응답)*

무효화는 두 갈래로 나눴다. 문서가 인제스트되거나 삭제되면 해당 kb_id가 걸린 캐시 엔트리를 예외를 흡수하며 best-effort로 지워, 캐시 무효화 실패가 인제스트/삭제 자체를 막지 않게 했다. 반대로 운영자가 수동으로 비우는 `DELETE /search/cache`는 Redis 장애를 흡수하지 않고 그대로 503으로 전파한다 — 명시적으로 부른 API라 실패를 숨기면 안 된다는 판단이다.

```python
from rag_api.query.search_cache import invalidate_kb_best_effort
invalidate_kb_best_effort(kb_id)
```
*([`src/rag_api/pipeline/steps/delete.py:72-73`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/pipeline/steps/delete.py#L72-L73), 삭제 완료 후 best-effort로 해당 KB 캐시 무효화)*

이 캐시는 Qdrant나 LlamaIndex가 대신 해주는 일이 아니다 — TTL과 엔트리 상한(FIFO eviction)까지 이 프로젝트가 Redis 위에 직접 얹은 레이어다. 결합 로직은 벡터 스토어에 최대한 위임하되, "같은 요청을 두 번 계산하지 않는다"는 이 프로젝트만의 문제는 이 프로젝트가 풀어야 했다.

## 9. 운영 트레이드오프

dense 하나만 인덱싱할 때와 달리, 이 프로젝트는 모든 point에 dense·sparse 벡터를 동시에 들고 있다 — 검색 품질을 얻는 대신 저장 공간을 더 쓰는 구조다.

```
                   저장 비용 ▲
                           │        ● (dense+sparse 동시 보관)
                           │       /
                           │      /
                           │_____/________________► 검색 품질
                          dense-only        hybrid
```

현재 `ensure_collection`은 `vectors_config`/`sparse_vectors_config`만 지정하고, HNSW(`m`, `ef_construct`)나 sparse index 옵션은 지정하지 않아 Qdrant 기본값을 그대로 쓴다.

```python
c.create_collection(
    collection_name=kb_id,
    vectors_config={
        DENSE_VECTOR_NAME: qmodels.VectorParams(
            size=vector_size, distance=qmodels.Distance.COSINE,
        ),
    },
    sparse_vectors_config={
        SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
            modifier=qmodels.Modifier.IDF,
        ),
    },
)
```
*([`src/rag_api/infra/qdrant.py:84-97`](https://github.com/cnapcloud/rag-api/blob/blog/qdrant-hybrid-search/src/rag_api/infra/qdrant.py#L84-L97), HNSW/sparse index 옵션 없이 collection 생성)*

데이터가 늘어나 저장 공간이나 검색 지연이 실제로 문제가 되면, 아래처럼 `hnsw_config`와 `on_disk` 옵션을 추가하는 방향으로 바꿀 필요가 있다.

```python
c.create_collection(
    collection_name=kb_id,
    vectors_config={
        DENSE_VECTOR_NAME: qmodels.VectorParams(
            size=vector_size,
            distance=qmodels.Distance.COSINE,
            hnsw_config=qmodels.HnswConfigDiff(
                m=8,               # Qdrant 기본값(16)보다 낮추면 메모리↓, 검색 정확도↓
                ef_construct=100,  # 기본값(100)보다 높이면 인덱싱 시간↑, 검색 품질↑
            ),
            on_disk=True,          # 벡터를 메모리 대신 디스크에 두어 RAM 사용량 절감
        ),
    },
    sparse_vectors_config={
        SPARSE_VECTOR_NAME: qmodels.SparseVectorParams(
            modifier=qmodels.Modifier.IDF,
            index=qmodels.SparseIndexParams(on_disk=True),
        ),
    },
)
```
*(개선 방향 예시, HNSW `m`/`ef_construct` 조정 + 벡터를 디스크에 두는 `on_disk` 옵션 추가 필요)*

`m`을 낮추면 그래프 연결이 성겨져 메모리는 줄지만 recall이 떨어지고, `ef_construct`를 높이면 인덱싱은 느려지는 대신 검색 품질이 올라간다 — 이 프로젝트 규모(수백만 벡터 이하)에서는 아직 기본값으로 충분하지만, KB 수와 문서량이 늘어나는 시점에 이 파라미터들부터 조정해볼 여지가 있다.

## 10. 마무리

이 프로젝트는 벡터 스토어로 Qdrant를 채택해, dense와 sparse 벡터를 하나의 point에 named vector로 같이 담고 하이브리드 조회를 컬렉션 레벨에서 그대로 받는 구조를 만들었다. 덕분에 결합 로직의 상당 부분을 애플리케이션 코드로 떠안지 않을 수 있었다 — 벡터 스토어를 고를 때 저울질했던 기준(결합 로직을 얼마나 떠안지 않아도 되는가)이 구현 단계에서도 그대로 맞아떨어진 셈이다. 그 위에 LlamaIndex로 KB 내부 결합(Relative Score Fusion)과 QdrantVectorStore 연결을, rerank API(jina/internal)로 후처리 재정렬 처리를 했다. 이 프로젝트가 직접 구현한 건 Qdrant도 LlamaIndex도 지원하지 않는 문제, 즉 여러 KB 결과의 RRF 병합(4.3장), parent-child auto-merge(5장), 검색 응답 캐시(8장)였다.

물론 그 효율을 공짜로 얻은 건 아니다. dense·sparse 벡터를 모든 point에 함께 들고 있는 구조라, dense-only일 때보다 저장 공간을 더 쓴다(9장). 같은 쿼리가 hybrid 결합과 rerank를 매번 다시 타는 비용도 Qdrant나 LlamaIndex가 대신 흡수해주지 않아, 검색 응답 캐시(exact 매칭 + 임베딩 유사도 기반 semantic 매칭, KB 인제스트/삭제 시 자동 무효화)를 이 프로젝트가 직접 얹어야 했다. HNSW와 sparse index도 아직 기본값 그대로다 — 데이터가 늘면 손봐야 한다는 걸 알면서도 지금 규모에서는 일단 미뤄뒀다.

그럼에도 이번 설계에서 가장 중요했던 판단은 "Qdrant를 쓸지 말지"가 아니라 "결합을 어느 레이어에서, 몇 단계로 나눌지"였다. 같은 collection 안의 결합과 여러 collection을 넘나드는 결합은 성격이 다른 문제였고, 이 둘을 하나의 fusion 로직으로 퉁치지 않고 레이어를 나눈 덕분에 Qdrant가 잘하는 일은 Qdrant에 맡기고, 이 프로젝트만 알아야 하는 일(RRF, auto-merge)은 애플리케이션 코드에 남겨둘 수 있었다.

하이브리드 검색을 벡터 DB 위에 얹어보려는 사람에게 남기고 싶은 말은 하나다. "어떤 벡터 DB가 제일 좋은가"보다 먼저 물어야 할 질문은 "내 결합 로직 중 어디까지를 벡터 DB에 맡기고, 어디부터를 내가 직접 구현할 것인가"다. 그 경계를 먼저 그어두면 제품 선택도, 이후의 튜닝도 훨씬 쉬워진다.

---

**참고 자료** (1장 벡터 스토어 비교 근거, 2026-09 기준)
- [The Best Vector Database in 2026: Qdrant vs Pinecone vs Weaviate vs Milvus vs pgvector](https://dev.to/darshit_01/the-best-vector-database-in-2026-qdrant-vs-pinecone-vs-weaviate-vs-milvus-vs-pgvector-3147)
- [Vector Database Comparison for RAG: Qdrant vs Weaviate vs Milvus](https://lushbinary.com/blog/vector-database-comparison-rag-qdrant-weaviate-milvus/)
- [Qdrant vs Weaviate vs Milvus: Which Vector Database for Your RAG Pipeline?](https://blog.elest.io/qdrant-vs-weaviate-vs-milvus-which-vector-database-for-your-rag-pipeline/)
- [2026 Milvus vs Qdrant: RAG Vector DB Decision](https://www.kunalganglani.com/blog/milvus-vs-qdrant)
- [Self-Hosted RAG in 2026: The Complete Guide](https://onyx.app/insights/self-hosted-rag)
- [RAG Production 2026: Pinecone vs Qdrant vs Weaviate Latency, Chunking, Hybrid Search Benchmarks](https://pooyagolchian.com/blog/rag-pipelines-production-vector-databases-2026/)
