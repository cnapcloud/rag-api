# 인프라 레이어 규칙

## 파일별 역할

| 파일 | 역할 | 상태 |
|------|------|------|
| `infra/minio.py` | MinIO 클라이언트, 이벤트 폴링, 파일 CRUD | 완성 |
| `infra/redis.py` | ETag 캐시 + KB/문서 메타데이터 CRUD | 부분 완성 |
| `infra/qdrant.py` | Qdrant 클라이언트, 컬렉션 관리, hybrid search | **미구현** |

## 싱글턴 클라이언트 패턴

모든 인프라 클라이언트는 모듈 레벨 싱글턴으로 관리.

```python
_client: SomeClient | None = None

def get_client() -> SomeClient:
    global _client
    if _client is None:
        cfg = get_settings().xxx
        _client = SomeClient(...)
    return _client
```

테스트에서는 `conftest.py`의 Mock 픽스처로 교체. 실제 연결 생성 금지.

## Redis 키 컨벤션

```
etag:{kb_id}:{doc_source}     # ETag 중복 방지 캐시
kb:{kb_id}                    # KB 메타데이터 (hash)
doc:{kb_id}:{doc_key}         # 문서 메타데이터 (hash)
docs:{kb_id}                  # KB 내 문서 목록 (set)
queue:ingest                  # API → Dagster 트리거 큐 (list)
```

## 파일 혼동 주의

**[주의] 2026-06-07 사고 전례**: `infra/redis.py`에 MinIO 코드가 복붙되는 사고 발생.
파일 수정 전 반드시 실제 내용 확인. `grep "class Minio\|import redis" src/infra/*.py`

## qdrant.py 구현 시 필요한 함수

```python
get_qdrant_client() → QdrantClient
ensure_collection(kb_id, vector_size)
upsert_chunks(kb_id, points: list[PointStruct])
delete_chunks_by_doc(kb_id, doc_key)  # payload 필터 사용
drop_collection(kb_id)
search(kb_id, query_dense, query_sparse, top_k, alpha) → list[ScoredPoint]
```

Qdrant hybrid search: `NamedVector` + `SparseVector` 조합, `alpha`로 가중치 조절.

## redis.py 미구현 함수 (backlog 참조)

`register_kb()`, `list_kb_ids()`, `delete_kb_meta()`,
`get_doc_status()`, `set_doc_status()`, `delete_doc_meta()`,
`list_docs()`, `list_docs_by_status()`, `ping()`
