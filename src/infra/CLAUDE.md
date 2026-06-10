# infra/ — 인프라 클라이언트 레이어

## 파일별 역할

| 파일 | 역할 |
|------|------|
| `s3.py` | S3(boto3) 클라이언트 팩토리, 이벤트 폴링, 파일 CRUD |
| `redis.py` | ETag 캐시 + KB/문서 메타데이터 CRUD (싱글턴 클라이언트) |
| `qdrant.py` | QdrantClient 팩토리, 컬렉션 관리, 청크 CRUD |

## 주의사항

- `redis.py`와 `s3.py`는 과거에 내용이 뒤바뀌는 버그가 있었음 (minio.py 시절). 파일을 새로 작성할 때 내용 확인 필수.

## Redis 키 컨벤션

```
etag:{kb_id}:{object_key}      # ETag 캐시
kb:{kb_id}                     # KB 메타데이터 (hash)
doc:{kb_id}:{doc_key}          # 문서 메타데이터 (hash)
docs:{kb_id}                   # 문서 목록 (set)
queue:ingest                   # Dagster 트리거 큐 (list, lpush/rpop)
```

## 클라이언트 싱글턴 패턴

```python
_client = None

def get_redis_client() -> redis.Redis:
    global _client
    if _client is None:
        cfg = get_settings().redis
        _client = redis.Redis(...)
    return _client
```

테스트에서는 `conftest.py`의 `mock_redis` / `mock_qdrant` / `mock_s3` 픽스처로 교체.
실제 연결을 테스트에서 직접 생성하지 말 것.

