# fastembed Model Cache Path

> **Superseded** — fastembed/onnxruntime was removed when sparse embedding was migrated to
> Qdrant server-side IDF. This document is retained for historical reference only.
> See [qdrant-idf-transition.md](../qdrant-idf-transition.md).

---

fastembed의 기본 캐시 경로는 `tempfile.gettempdir()` 기반으로 결정된다. Docker 컨테이너에서는 `/tmp/fastembed_cache`가 되며, `/tmp`는 컨테이너 재시작마다 초기화되므로 **매번 모델을 재다운로드**한다.

**해결**

`FASTEMBED_CACHE_PATH` 환경변수로 캐시 경로를 `/tmp` 밖으로 지정하고, 이미지 빌드 시 모델을 미리 포함시킨다.

```dockerfile
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache

# 의존성 설치 후, 소스 복사 전에 실행 (레이어 캐시 활용)
RUN python -c "from fastembed import SparseTextEmbedding; SparseTextEmbedding('Qdrant/bm25')"
```

`Qdrant/bm25` 모델 크기는 약 104KB로 이미지에 포함시켜도 부담 없다.

캐시 경로 결정 로직 (`fastembed/common/utils.py`):
```python
default_cache_dir = os.path.join(tempfile.gettempdir(), "fastembed_cache")
cache_path = Path(os.getenv("FASTEMBED_CACHE_PATH", default_cache_dir))
```
