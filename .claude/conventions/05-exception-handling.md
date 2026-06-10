# Exception Handling Conventions

## Exception 계층 원칙

레이어마다 사용하는 exception 타입을 구분한다.

| 레이어 | 사용 exception | 목적 |
|--------|---------------|------|
| Pipeline Op (`pipeline/ops/`) | `ValueError` | 잘못된 인자, 지원하지 않는 형식/전략 |
| Infra (`infra/`) | SDK 예외를 `RuntimeError`로 wrapping | 외부 연결·I/O 실패 |
| API Router (`api/routers/`) | `HTTPException` | 클라이언트에 전달되는 HTTP 오류 |
| Dagster Op 래퍼 (`dagster_pipeline/ops/`) | `ValueError` re-raise | Op에서 온 예외를 그대로 전파 |

## Exception 메시지는 영어로

`raise` 메시지도 로그 메시지와 동일하게 영어로 작성.

```python
# 잘못됨
raise ValueError(f"알 수 없는 청킹 전략: {strategy}")
raise HTTPException(status_code=400, detail="kb_ids는 최소 1개 이상이어야 합니다.")

# 올바름
raise ValueError(f"Unknown chunking strategy: {strategy}")
raise HTTPException(status_code=400, detail="kb_ids must have at least one entry.")
```

## Pipeline Op: ValueError 전용

Op 함수는 잘못된 인자·설정에 대해서만 `ValueError`를 발생시킨다.
외부 인프라 오류는 infra 레이어에서 처리하므로 Op에서 직접 잡지 않는다.

```python
# 올바름
def chunk(documents, strategy, chunk_size, chunk_overlap):
    if strategy not in ("recursive", "semantic", "document_aware"):
        raise ValueError(f"Unknown chunking strategy: {strategy}")
    ...

# 잘못됨 — Op에서 infra 오류를 잡으면 순수 함수 원칙 위반
def embed(nodes):
    try:
        return _call_ollama(nodes)
    except requests.ConnectionError:  # 금지
        ...
```

## Infra 레이어: SDK 예외 wrapping

외부 SDK(MinIO S3Error, QdrantException 등)는 infra 함수 내에서만 잡고,
`RuntimeError`로 wrapping해서 상위 레이어에 전파한다.

```python
# 올바름
def download_object(bucket, key):
    try:
        return minio_client.get_object(bucket, key)
    except S3Error as e:
        logger.error("MinIO download failed: bucket=%s key=%s err=%s", bucket, key, e)
        raise RuntimeError(f"Failed to download object: {key}") from e

# 잘못됨 — SDK 예외를 그대로 노출
def download_object(bucket, key):
    return minio_client.get_object(bucket, key)  # S3Error가 직접 전파됨
```

## API Router: HTTPException 변환

비즈니스 로직 예외(ValueError, RuntimeError)를 클라이언트용 HTTPException으로 변환한다.
변환 전에 반드시 `logger.exception()` 또는 `logger.error()`로 기록한다.

```python
# 올바름
@router.post("/api/kb/{kb_id}/docs/upload")
async def upload_doc(kb_id: str, ...):
    try:
        result = await run_pipeline(kb_id, ...)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        logger.error("Upload failed: kb=%s err=%s", kb_id, e)
        raise HTTPException(status_code=500, detail="Internal pipeline error.") from e
```

## Silent swallow 금지

예외를 잡고 아무것도 하지 않는 패턴은 금지.
로그 기록 후 re-raise하거나 명시적인 fallback 값을 반환해야 한다.

```python
# 금지
try:
    result = rerank(nodes)
except Exception:
    pass  # 오류 은폐

# 금지
try:
    result = rerank(nodes)
except Exception:
    return []  # 이유 없는 빈 반환

# 올바름 — fallback이 의도된 동작이면 이유를 로그에 남긴다
try:
    result = rerank(nodes)
except Exception as e:
    logger.warning("Reranker unavailable, falling back to RRF scores: %s", e)
    return nodes
```

## `except Exception` 패턴

불가피하게 `Exception`을 넓게 잡아야 할 때는 `logger.exception()`으로 스택 트레이스를 기록하고 re-raise한다.

```python
# 올바름 — runner.py, sensor 등 최상위 진입점에서만 허용
try:
    run_pipeline(kb_id, object_key)
except Exception as e:
    logger.exception("Pipeline failed: kb=%s key=%s", kb_id, object_key)
    raise

# 잘못됨 — 중간 레이어에서 Exception을 넓게 잡고 삼킴
try:
    chunk(docs, ...)
except Exception:
    logger.error("Error")  # 스택 트레이스 없음, re-raise도 없음
```

## `asyncio.gather`의 return_exceptions

병렬 실행 결과에 `return_exceptions=True`를 쓸 때는 반드시 결과를 검사하고 오류를 처리한다.

```python
results = await asyncio.gather(*tasks, return_exceptions=True)

errors = [r for r in results if isinstance(r, Exception)]
if errors:
    logger.error("Gather failed: %d/%d tasks errored", len(errors), len(tasks))
    raise RuntimeError(f"Retrieval failed for {len(errors)} KB(s).")
```

## `from e` chaining 필수

예외를 변환할 때 원인 보존을 위해 `raise ... from e`를 사용한다.

```python
# 올바름
raise HTTPException(status_code=500, detail="...") from e
raise RuntimeError("...") from e

# 잘못됨 — 원인 체인이 끊김
raise HTTPException(status_code=500, detail="...")
```

## Health check 예외

`/ready` 엔드포인트처럼 여러 인프라를 순차 점검하는 경우,
각 항목을 독립적으로 잡고 결과를 집계한다. re-raise 금지.

```python
# 올바름
status = {}
try:
    ping_redis()
    status["redis"] = "ok"
except Exception as e:
    status["redis"] = f"error: {e}"

try:
    ping_qdrant()
    status["qdrant"] = "ok"
except Exception as e:
    status["qdrant"] = f"error: {e}"
```
