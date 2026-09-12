---
name: logging
description: 로거 선언·레벨·메시지 포맷 요약(+원본 링크). implementer가 logger 호출을 쓰거나 예외를 로깅할 때 사용.
---

# Logging (요약)

전체 내용은 `docs/internal/architecture/application.md` §4(로깅 전략)에 있다 — 이 스킬은
그 문서를 대체하지 않고 자주 쓰는 핵심만 압축한다. 모호하면 원본 문서를 직접 읽는다.

## 기본 원칙

- 모든 모듈: `logger = logging.getLogger(__name__)`.
- 모든 메시지 영어, `%s`/`%d` 스타일 포맷(f-string 금지 — 레벨 미달 시에도 문자열이
  생성되는 것을 방지), 관련 컨텍스트(`kb_id`, `doc_id`, `strategy` 등) 포함.
- 레벨은 `settings.yaml`의 `logging.level`에서 읽는다 — 코드에서 레벨 하드코딩 금지.

```python
# 올바름
logger.info("Chunking done: code=%d text=%d nodes=%d", len(code_docs), len(text_docs), len(nodes))
# 금지
logger.info(f"청킹 완료: {len(nodes)}개")   # 한국어, f-string
```

## Dagster UI 노출

| 방식 | Dagster UI 노출 | 사용 위치 |
|---|---|---|
| `context.log.info()` | 항상 | Dagster op 래퍼 (`defs/ops/`) |
| `logging.getLogger(__name__)` | 기본 X, `managed_python_loggers` 설정 시 O | 순수 함수 (`pipeline/steps/`) — `docker/dagster.yaml`에서 활성화 |

## 레벨 기준

| 레벨 | 사용 상황 |
|---|---|
| `DEBUG` | 상세 내부 상태 (개발 시) |
| `INFO` | 주요 처리 단계 완료 |
| `WARNING` | silent-fail 상황, 예상 가능한 오류 |
| `ERROR` | 처리 실패, 예외 스택 트레이스 포함 |

## 부팅 순서 (application.md에는 없는, 구현 세부사항)

`rag_api.logging.setup_logging()`이 CLI 진입점(`main.py`)에서 다른 임포트보다 먼저
호출되어 ROOT 로거를 선점하고 `settings.logging.names`의 네임스페이스(`rag_api`)에
`propagate=False` 핸들러를 붙인다 — uvicorn 등 서드파티가 나중에 자체 `basicConfig()`를
불러도 포맷이 뒤바뀌지 않는다. idempotent라 여러 번 호출돼도 안전하다.

## 예외 로깅

catch 후 re-raise할 때는 `logger.error()`로 컨텍스트를 기록한 뒤 raise (`from e`
chaining은 `exception-handling` 스킬 참고). silent-fail 정책에 따라 swallow하는 경우는
`logger.warning()`으로 기록한다.

```python
except ClientError as e:
    logger.error("S3 download failed: bucket=%s key=%s err=%s", bucket, key, e)
    raise RuntimeError(f"Failed to download object: {key}") from e
```
