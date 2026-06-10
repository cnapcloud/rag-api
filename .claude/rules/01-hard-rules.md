# Hard Rules — 절대 금지 사항

## 1. 설정 하드코딩 금지

```python
# 금지
CHUNK_SIZE = 1024
REDIS_HOST = "redis"

# 올바름
cfg = get_settings().chunking
chunk_size = cfg.chunk_size
```

`get_settings()`를 항상 사용. `settings.yaml`이 단일 진실 소스.

---

## 2. `from src.` import 금지

```python
# 금지
from src.config.settings import get_settings

# 올바름
from config.settings import get_settings
```

---

## 3. 테스트에서 실제 인프라 연결 금지

```python
# 금지
redis_client = redis.Redis(host="localhost")  # 테스트에서

# 올바름
def test_something(mock_redis):  # conftest.py 픽스처 사용
    ...
```

---

## 4. infra/ 파일 수정 전 내용 확인 필수

`infra/redis.py`에 MinIO 코드가 복붙된 사고 전례(2026-06-07).
파일 수정 전 반드시 Read 또는 grep으로 내용 확인.

```bash
grep -n "class\|def\|import" src/infra/qdrant.py | head -20
```

---

## 5. Op 함수에 Dagster context 주입 금지

```python
# 금지
def chunk(context: OpExecutionContext, documents):
    ...

# 올바름 — Dagster 래퍼에서 context 처리
def chunk(documents, strategy, chunk_size, chunk_overlap) -> list[BaseNode]:
    ...
```

Op은 순수 함수. Dagster 의존성은 `dagster_pipeline/ops/` 래퍼에서만.

---

## 6. `infra/minio.py`와 `infra/redis.py` 역할 혼동 금지

| 파일 | 담당 |
|------|------|
| `minio.py` | 파일 저장/조회, 이벤트 폴링 |
| `redis.py` | ETag 캐시, KB/문서 메타데이터 |
| `qdrant.py` | 벡터 저장/검색 |

---

## 7. 이모지 사용 금지

코드, 문서, 로그 어디에도 이모지 사용 금지.

```python
# 금지
logger.info("완료")
logger.warning("경고")

# 올바름
logger.info("done")
logger.warning("warning: ...")
```

마크다운 문서에서도 이모지 대신 텍스트 레이블 사용. (HIGH / MED / LOW 등)

---

## 8. 로그 메시지는 영어로

`logger.*()` 호출과 `print()` 출력 모두 반드시 영어로 작성.

```python
# 금지
logger.info("청킹 완료: 전략=%s", strategy)
print(f"[1/5] 파싱 중: {file_path}")

# 올바름
logger.info("Chunking done: strategy=%s", strategy)
print(f"[1/5] Parsing: {file_path}")
```
