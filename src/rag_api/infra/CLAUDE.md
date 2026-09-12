# infra/ — 인프라 클라이언트 레이어

## 파일별 역할

| 파일 | 역할 |
|------|------|
| `postgres.py` | 커넥션 풀, 마이그레이션, KB/문서/커넥터 메타데이터 CRUD |
| `qdrant.py` | QdrantClient 팩토리, 컬렉션 관리, 청크 CRUD |
| `redis.py` | ETag 캐시, 이벤트 큐(lpush/rpop) |
| `s3.py` | S3(boto3) 클라이언트 팩토리, 파일 CRUD |
| `dagster_utils.py` | Dagster GraphQL API — workspace reload, run terminate |
| `crypto.py` | 커넥터 config 필드 암호화/복호화/마스킹 (Fernet) |

## 주의사항

- `redis.py`와 `s3.py`는 과거에 내용이 뒤바뀌는 버그가 있었음 (minio.py 시절). 파일을 새로 작성할 때 내용 확인 필수.
- `upload_object`의 `metadata` 값은 `x-amz-meta-*` HTTP 헤더로 전송되므로 ASCII만 허용됨 — 한글 등 non-ASCII 값(예: source_uri)을 그대로 넣으면 boto3 `ParamValidationError`. `upload_object` 내부에서 자동으로 percent-encode하므로 커넥터 코드에서 별도 처리 불필요, 새 metadata 키 추가 시에도 이 인코딩을 우회하지 말 것.
- `dagster_utils.py`의 함수는 `queue_worker.enabled = true`일 때 no-op. Dagster 없이 동작하는 배포 모드를 고려할 것.

## Redis 키 컨벤션

```
etag:{kb_id}:{doc_source}      # ETag 캐시
queue:upload                   # ingest 이벤트 큐 (list, lpush/rpop)
queue:delete                   # delete 이벤트 큐 (list, lpush/rpop)
queue:upload:delay             # ingest 재시도 대기 (sorted set, score=timestamp)
queue:delete:delay             # delete 재시도 대기 (sorted set, score=timestamp)
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

테스트에서는 `conftest.py`의 `mock_redis` / `mock_qdrant` / `mock_minio` / `mock_postgres`
픽스처로 교체. 실제 연결을 테스트에서 직접 생성하지 말 것.

