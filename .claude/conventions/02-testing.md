# 테스트 패턴

## 기본 원칙

- 외부 인프라(Redis, Qdrant, MinIO, Ollama)는 **항상 Mock 사용**
- `conftest.py`의 픽스처를 우선 사용
- Op 함수는 Dagster context 없이 직접 호출 가능

## 실행 명령어

```bash
# 단위 테스트
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ -v

# 전체 테스트
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v

# Makefile 단축키
make test
```

## conftest.py 픽스처

| 픽스처 | 역할 |
|--------|------|
| `mock_redis` | In-memory dict 기반 FakeRedis |
| `mock_qdrant` | MagicMock Qdrant 클라이언트 |
| `mock_minio` | MagicMock MinIO 클라이언트 |
| `mock_embed_model` | Mock LlamaIndex Embedding (1024차원) |
| `mock_dagster_resources` | Dagster 통합 테스트용 전체 Mock |

## 청킹 테스트 주의사항

`SentenceSplitter`는 **공백/문장 경계**로 분할. 연속 문자는 단일 청크로 반환됨.

```python
# 잘못됨 — "A" * 3000은 분할 안 됨
docs = [Document(text="A" * 3000)]
nodes = chunk(docs, strategy="recursive", chunk_size=512)
assert len(nodes) > 1  # 실패!

# 올바름 — 공백 있는 텍스트 + 작은 chunk_size
docs = [Document(text="sample text " * 500)]
nodes = chunk(docs, strategy="recursive", chunk_size=128, chunk_overlap=16)
assert len(nodes) > 1  # 통과
```

## Mock patch 패턴

```python
# validate.py가 redis_infra.get_doc_etag를 사용하는 경우
with patch("pipeline.ops.validate.redis_infra.get_doc_etag", return_value=None):
    from pipeline.ops.validate import validate
    assert validate("kb-test", "doc.pdf", "etag-abc") is True
```

patch 대상은 **호출하는 쪽의 모듈 경로** 기준 (import한 위치).

## asyncio 테스트

`pyproject.toml`에 `asyncio_mode = "auto"` 설정됨. `@pytest.mark.asyncio` 불필요.
