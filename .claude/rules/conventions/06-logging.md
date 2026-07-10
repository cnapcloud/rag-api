---
paths:
  - "src/**/*.py"
---

# Logging Convention

## 로거 선언

모든 모듈은 `logging.getLogger(__name__)`로 로거를 얻는다.

```python
import logging

logger = logging.getLogger(__name__)
```

`rag_api.logging.setup_logging()`이 CLI 진입점(`main.py`)에서 다른 임포트보다 먼저 호출되어
ROOT 로거와 `settings.logging.names`에 나열된 최상위 네임스페이스(`rag_api`)를 미리 구성하므로,
각 모듈은 별도 설정 없이 표준 `logging.getLogger(__name__)`만 쓰면 된다. `rag_api.logging`은
`get_logger()` 헬퍼도 제공하지만, 실제 코드베이스 전체가 표준 `logging.getLogger(__name__)`를
쓰고 있으므로 새 코드도 이 패턴을 따른다.

## 왜 setup_logging()이 먼저 호출되어야 하는가

`setup_logging()`은 `logging.basicConfig()`로 ROOT 로거를 먼저 선점한다. mcp의 FastMCP나
uvicorn 등 서드파티 라이브러리가 나중에 자체 `basicConfig()`를 호출해도 root에 이미 핸들러가
있으면 no-op이 되므로, 로그 포맷이 Rich 등으로 뒤바뀌지 않는다. 이후
`settings.logging.names`에 있는 각 최상위 네임스페이스(`rag_api`)에 별도 핸들러를 붙이고
`propagate = False`로 설정해 ROOT 재구성의 영향을 받지 않게 한다. `main.py`에서 다른 임포트보다
먼저 `setup_logging()`을 호출하는 순서를 지켜야 한다.

## 로그 레벨 설정

로그 레벨은 `settings.yaml`의 `logging.level`에서 읽는다. `setup_logging()`은 idempotent —
여러 번 호출돼도 네임스페이스별로 한 번만 핸들러가 등록된다(`_configured_namespaces`,
`_root_configured` 가드). 코드 어디서도 레벨 하드코딩 금지.

```yaml
# settings.yaml
logging:
  level: INFO        # DEBUG | INFO | WARNING | ERROR
  names: [rag_api]
```

## 레벨 사용 기준

| 레벨 | 사용 상황 |
|------|----------|
| `DEBUG` | 상세 내부 상태, 개발 디버깅 |
| `INFO` | 정상 흐름의 주요 이벤트 (파이프라인 단계 완료, 업서트 결과 등) |
| `WARNING` | 복구 가능한 예외 상황 (silent-fail 정책, fallback 발생) |
| `ERROR` | 처리 실패, 예외 발생 (propagate 전 컨텍스트 기록) |

## 메시지 규칙

- **영어만** 사용. 한국어, 이모지 금지.
- `%s`/`%d` 스타일 포맷 사용 (f-string 금지 — 레벨 미달 시 문자열 생성 방지. 코드베이스 전체가 이 스타일).
- 관련 컨텍스트(`kb_id`, `doc_id`, `strategy` 등)를 메시지에 포함.

```python
# 올바름
logger.info("Chunking done: code=%d text=%d nodes=%d", len(code_docs), len(text_docs), len(nodes))
logger.warning("Qdrant chunk deletion failed (ignored): doc_id=%s err=%s", doc_id, e)

# 금지
logger.info(f"청킹 완료: {len(nodes)}개")   # 한국어, f-string
logger.info("Chunking done")                  # 컨텍스트 없음
```

## 예외 로깅

예외를 catch하고 re-raise할 때는 `logger.error()`로 컨텍스트를 기록한 후 raise
(`from e` chaining은 `conventions/05-exception-handling.md` 참조). silent-fail 정책에 따라
swallow하는 경우는 `logger.warning()`으로 기록.

```python
# re-raise 전 기록
except S3Error as e:
    logger.error("MinIO download failed: bucket=%s key=%s err=%s", bucket, key, e)
    raise RuntimeError(f"Failed to download object: {key}") from e

# silent-fail (정책에 따른 예외적 경우만)
except S3Error as e:
    logger.warning("MinIO object deletion failed (ignored): kb=%s key=%s err=%s", kb_id, key, e)
```
