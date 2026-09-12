---
name: exception-handling
description: RAGError 계층과 레이어별 예외 처리 규칙 요약(+원본 링크). implementer가 예외를 던지거나 잡는 코드를 쓸 때 사용.
---

# Exception Handling (요약)

전체 내용은 `docs/internal/architecture/application.md` §3(예외 처리 전략)에 있다 — 이
스킬은 그 문서를 대체하지 않고 자주 쓰는 핵심만 압축한다. 클래스 정의 자체는
`src/rag_api/exceptions.py`가 원본이다. 모호하면 둘 다 직접 읽는다.

## 예외 계층

```
RAGError (base)
├── ConfigError           → HTTP 500
├── IngestValidationError → HTTP 422
├── NotFoundError         → HTTP 404
└── ConflictError         → HTTP 409
```

모든 도메인 예외 클래스는 `src/rag_api/exceptions.py`에만 정의한다 — 다른 곳에서 새
예외 클래스를 만들지 않는다. 라이브러리 예외는 `api/app.py`에서 래퍼 없이 직접 HTTP로
매핑한다: `botocore.exceptions.ClientError`(S3) → 502, `redis.RedisError` → 503,
`psycopg.Error`(Postgres) → 503.

## 레이어별 규칙

| 레이어 | 규칙 |
|---|---|
| `infra/` | 라이브러리 예외를 도메인 예외로 감싸지 않고 그대로 propagate. `ping()`류만 예외(swallow, `bool` 반환). 설정 레벨 오류만 `ConfigError`. |
| `pipeline/steps/` | 순수 함수, `HTTPException` 금지. 사용자가 고칠 수 있는 입력 오류 → `IngestValidationError`, 운영자가 고쳐야 하는 설정 오류 → `ConfigError`. bare `ValueError` 금지. |
| `api/routers/` | `Exception`을 넓게 catch하지 않는다. 비즈니스 404/409 → `NotFoundError`/`ConflictError`. 라이브러리 예외는 아래 silent-fail 정책에 해당하는 곳에서만 catch. |
| `api/app.py` | HTTP 상태 코드 결정의 유일한 지점 — router/infra에 흩어놓지 않는다. |

## Silent-fail 정책 (표에 없는 상황은 전부 propagate)

| 상황 | 정책 |
|---|---|
| Qdrant/S3 삭제 실패 (정리 중) | warning 로그, 계속 진행 |
| 다중 KB 검색 중 특정 KB 실패 | error 로그, 해당 KB만 빈 결과 반환 |
| Jina reranker API 실패 | warning 로그, RRF 점수 fallback |
| 시작 시 인프라 초기화 실패 | warning 로그, 서버 계속 기동 |

## 메시지 규칙 (application.md에는 없는, 코드 레벨 규칙)

- 모든 예외 메시지는 영어. 관련 컨텍스트(`kb_id`, `doc_source` 등) 포함.
- `from e` chaining 필수 — `raise DomainError(...) from None` 금지.
- 위 표에 없는 상황을 silent swallow하지 않는다.

```python
# 올바름
raise IngestValidationError(f"File too large: {size_mb:.1f} MB > {max_mb} MB") from e

# 금지 — from e 누락, 한국어 메시지
raise ConfigError("청킹 전략 오류")
```
