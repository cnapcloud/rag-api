---
name: conventions
description: 하드 룰 상세(설정/infra/순수함수/이모지/로그/커밋) + 테스트 작성 가이드. CLAUDE.md "하드 룰"은 이 스킬로의 목차일 뿐이니 실제로 코드를 쓰기 전엔 여기를 확인한다.
---

# Implementation Conventions

`CLAUDE.md`의 "하드 룰" 섹션은 여기로의 한 줄 목차다 — 실제 상세(왜, 코드 예시, 예외
케이스)는 전부 이 스킬에 있다. 모호하면 이 스킬을 우선 참고하고, 그래도 부족하면
`CLAUDE.md`/코드를 직접 읽는다.

## 설정 하드코딩 금지

`get_settings()`를 항상 사용한다. `settings.yaml`이 단일 진실 소스다.

```python
# 금지
CHUNK_SIZE = 1024
# 올바름
chunk_size = get_settings().chunking.chunk_size
```

## Import 경로

`from src.` 금지, `rag_api` 절대 경로로 import — 상세는 `import-paths` 스킬.

## 테스트에서 실제 인프라 연결 금지 + 작성 가이드

외부 인프라(Redis, Qdrant, MinIO/S3, Postgres)는 항상 Mock 사용 — `tests/conftest.py`의
`mock_redis`/`mock_qdrant`/`mock_minio`/`mock_postgres` 픽스처를 쓴다. 테스트 안에서 직접
`redis.Redis(...)` 같은 실제 클라이언트를 생성하지 않는다.

파일/함수 구성 (기존 테스트 코드에서 뽑은 컨벤션):
- 파일 위치: `tests/unit/test_<module>.py`(순수 함수/컴포넌트), `tests/dagster/`
  (Dagster op/job), `tests/integration/`(여러 레이어를 걸치는 흐름) — 대상 소스 파일과
  1:1로 매칭되는 이름을 쓴다.
- 함수명은 `test_<대상>_<기대 동작>` 형태로 서술적으로 짓는다 (예:
  `test_missing_base_url_raises`, `test_chunk_single_short_document`). 무엇을
  검증하는지 한 줄 docstring을 단다 — 테스트 코드의 docstring/주석은 한국어도 가능하다
  (영어 필수는 `logger.*()`/`print()` 출력에만 적용, 아래 참고).
- 한 대상 함수/메서드에 관련 케이스가 여러 개 쌓이면 `class Test<대상>:`로 묶는다
  (`test_confluence_connector.py`의 `TestProcessPage` 등 참고).
- 입력 조합만 다르고 로직이 같은 케이스는 `@pytest.mark.parametrize`로 정리한다.
- 예외가 기대되는 경로는 `pytest.raises(<구체적 예외 타입>)`으로 검증한다 — 예외 타입은
  `exception-handling` 스킬의 계층을 따른다.

```bash
uv run pytest -q                          # 전체 (= make test)
uv run pytest -q tests/unit/test_foo.py   # 특정 파일만
```

## `infra/` 파일 역할 혼동 금지 + 수정 전 확인 필수

| 파일 | 담당 |
|------|------|
| `s3.py` | 파일 저장/조회 (S3 호환, MinIO) |
| `redis.py` | ingest/delete 이벤트 큐 |
| `postgres.py` | KB/문서 메타데이터 CRUD, 마이그레이션 |
| `qdrant.py` | 벡터 저장/검색 |
| `crypto.py` | 커넥터 설정 시크릿 암복호화 |
| `dagster_utils.py` | Dagster GraphQL 원격 제어 |

`infra/redis.py`에 MinIO 코드가 복붙된 사고 전례(2026-06-07)가 있다. `infra/` 파일을
고치기 전에는 task.md에 적힌 대상 파일이라도 반드시 Read 또는 grep으로 실제 내용을 먼저
확인한다.

## Step 함수는 순수 함수로 유지

`pipeline/steps/`의 함수에 Dagster `context`를 주입하지 않는다. Dagster 의존성은
`defs/ops/` 래퍼에서만 다룬다.

```python
# 금지
def chunk(context: OpExecutionContext, documents): ...
# 올바름 — Dagster 래퍼에서 context 처리, step은 순수 함수
def chunk(documents, strategy, chunk_size, chunk_overlap) -> list[BaseNode]: ...
```

## 이모지 금지, 로그/print 영어, 커밋 트레일러 금지

세션 종류와 무관하게 항상 적용되는 규칙이라 `CLAUDE.md` "하드 룰"에 그대로 있다 — 여기서
다시 베끼지 않는다. 로그 레벨/포맷 세부 규칙(`%s` 포맷, 컨텍스트 포함 등)만 `logging`
스킬에 별도로 있다.
