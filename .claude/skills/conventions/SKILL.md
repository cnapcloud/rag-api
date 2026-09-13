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

외부 인프라(Redis, Qdrant, MinIO/S3, Postgres)는 항상 `tests/conftest.py`의
`mock_redis`/`mock_qdrant`/`mock_minio`/`mock_postgres` 픽스처로 Mock한다 — 테스트 안에서
직접 `redis.Redis(...)` 같은 실제 클라이언트를 생성하지 않는다.

파일 위치는 대상 소스 파일과 1:1로 매칭: `tests/unit/test_<module>.py`(순수 함수/컴포넌트),
`tests/dagster/`(Dagster op/job), `tests/integration/`(여러 레이어를 걸치는 흐름).

**필수 — spec task(task.md) 기반으로 새로 추가/변경하는 테스트마다 예외 없이 둘 다 붙인다**
(기존에 있던, 이번 task와 무관한 테스트는 건드리지 않는 한 소급 적용하지 않는다):

- AC 태그 주석 한 줄 — 형식 `# AC: <AC-ID> (<spec 폴더명>/<Task-ID>)`. 테스트 함수/메서드
  바로 위에 쓴다. 하나의 AC를 여러 테스트가 나눠 검증하면 각 테스트마다 동일한 태그를 반복해서
  붙인다.
- 한 줄 docstring — 테스트가 "무엇을 검증하는지"를 함수명보다 구체적으로 서술한다.

이 두 가지를 빠뜨리면 리뷰/검증 단계에서 컨벤션 위반으로 되돌아온다. 나머지 컨벤션
(함수명/클래스 묶음/parametrize/예외 검증)은 아래 예시 수준을 따르면 충분하다 — 테스트
코드의 docstring/주석은 한국어도 가능하다(영어 필수는 `logger.*()`/`print()` 출력에만
적용):

```python
class TestSearchCacheLookup:
    # AC: F3-5 (US-53-search-cache/T3)
    def test_semantic_hit_above_threshold(self):
        """유사도가 threshold 이상이면 semantic 캐시 hit을 반환한다."""
        ...

    @pytest.mark.parametrize("match_mode", ["exact", "semantic"])
    def test_exact_mode_skips_embedding(self, match_mode):
        """exact 모드에서는 임베딩 계산이 전혀 호출되지 않는다."""
        ...

    def test_missing_base_url_raises(self):
        """base_url 누락 시 ConfigError를 던진다(예외 타입은 exception-handling 스킬 참고)."""
        with pytest.raises(ConfigError):
            ...
```

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
