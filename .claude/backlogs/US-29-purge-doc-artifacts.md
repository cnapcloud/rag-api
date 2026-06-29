---
id: US-29
title: purge_doc_artifacts 공통 함수 추출 + pipeline/ops/utils/ 패키지 정리
status: todo
---

# US-29 purge_doc_artifacts 공통 함수 추출

## 목표

`failed` / `outdated` / `deleted` 상태 전환 시 실행되는 Qdrant 청크 삭제·S3 파일 삭제·dedup 밴드 삭제가
`meta.py`, `delete.py`, `verdict.py` 세 파일에 흩어져 반복된다.
이를 단일 `purge_doc_artifacts` 함수로 통합하고, 이 기회에 파이프라인 step이 아닌 유틸리티 파일들을
`pipeline/ops/utils/` 패키지로 모아 디렉토리 구조를 정리한다.

## 배경

현재 call site:

| 파일 | 호출 조합 |
|------|----------|
| `meta.py::set_failed` | Qdrant + simhash + minhash (best-effort swallow) |
| `delete.py::_delete_db_record` soft delete | simhash + minhash (propagate) |
| `verdict.py::handle_title_changed` existing | simhash + minhash (propagate) |
| `verdict.py::handle_similar` incoming wins | Qdrant + simhash + minhash (propagate) |
| `verdict.py::handle_similar` incoming loses | simhash + minhash (propagate) |

simhash + minhash는 항상 쌍으로 삭제되어야 하는데 각 call site마다 두 줄씩 반복.

## 구현 방향

### 1단계: `pipeline/utils/` 패키지 신설 및 파일 이동

파이프라인 6단계 흐름(validate→parse→chunk→embed→upsert→meta)에 해당하지 않는
유틸리티 파일들을 `pipeline/utils/`로 이동한다.

| 현재 위치 | 이동 후 위치 | 이유 |
|-----------|-------------|------|
| `pipeline/ops/upsert.py` | `pipeline/utils/upsert.py` | Qdrant write 헬퍼, pipeline step이 아님 |
| `pipeline/ops/sparse.py` | `pipeline/utils/sparse.py` | BM25 임베딩 헬퍼 |
| `pipeline/ops/runner.py` | `pipeline/utils/runner.py` | CLI/테스트용 래퍼 |
| `pipeline/ops/dedup/tokenizer.py` | `pipeline/utils/tokenizer.py` | 토크나이저 유틸리티 |
| `pipeline/ops/dedup/types.py` | `pipeline/utils/types.py` | 공유 타입 정의 |

이동 후 구조:

```
pipeline/
  enqueue.py   queue_worker.py   source_uri.py
  ops/          (validate, parse, chunk, embed, meta, delete, dedup/)
  utils/        (upsert, sparse, runner, tokenizer, types, purge)
```

### 2단계: `pipeline/utils/purge.py` 신규 추가

#### 함수 시그니처

```python
def purge_doc_artifacts(
    doc_id: str,
    kb_id: str = "",
    storage_key: str = "",
    *,
    include_chunks: bool = True,
    swallow: bool = False,
) -> None:
    """Remove Qdrant chunks, S3 file, and dedup bands for a document.

    include_chunks: Qdrant 벡터 삭제 (kb_id 없으면 스킵)
    storage_key: S3 파일 삭제 (비어있으면 스킵). ClientError는 항상 swallow.
    swallow: True면 각 operation 실패 시 warning 로그 후 계속, False면 예외 전파.
    """
```

#### Call site별 변경

| 파일 | 변경 후 |
|------|---------|
| `meta.py::set_failed` | `purge_doc_artifacts(doc_id, kb_id, swallow=True)` |
| `delete.py::_delete_db_record` soft delete | `purge_doc_artifacts(doc_id, include_chunks=False)` |
| `delete.py::_delete_db_record` hard delete | `purge_doc_artifacts(doc_id, kb_id, storage_key)` — `hard_delete_doc` 호출 직전 |
| `verdict.py::handle_title_changed` existing | `purge_doc_artifacts(duplicate_doc_id, include_chunks=False)` |
| `verdict.py::handle_similar` incoming wins | `purge_doc_artifacts(duplicate_doc_id, kb_id, include_chunks=True)` |
| `verdict.py::handle_similar` incoming loses / no duplicate | `purge_doc_artifacts(doc_id, include_chunks=False)` |

### 변경하지 않는 것

- `delete.py::_delete_qdrant_chunks` — indexed vs 기타에 따라 propagate/swallow 분기, 전용 로직 유지
- `connectors.py::_cascade_delete` — hard_delete_doc CASCADE 처리, 밴드 삭제 불필요

### S3 삭제 정책

- S3 ClientError는 `swallow` 플래그와 무관하게 항상 warning 로그 후 continue
  (기존 `_delete_s3_object` 동작과 동일, 예외처리 컨벤션 silent-fail 정책)
- `storage_key` 비어있으면 S3 스킵

## 테스트

### 신규 단위 테스트 (`tests/unit/test_purge_doc_artifacts.py`)

- `swallow=True`: 각 operation 실패 → warning + 나머지 계속
- `include_chunks=False`: Qdrant 함수 미호출
- `include_chunks=True` + `kb_id=""`: Qdrant 함수 미호출 (guard)
- `storage_key` 있으면: S3 삭제 호출
- `storage_key` 없으면: S3 미호출
- `swallow=False` + exception: 예외 전파

### 기존 테스트

파일 이동으로 인한 import 경로 변경:
- `from pipeline.ops.upsert import ...` → `from pipeline.utils.upsert import ...`
- `from pipeline.ops.dedup.tokenizer import ...` → `from pipeline.utils.tokenizer import ...`
- `from pipeline.ops.dedup.types import ...` → `from pipeline.utils.types import ...`

`verdict.py` 테스트의 `infra.postgres.delete_simhash_bands` patch 경로는 변경 불필요.

전체 통과 확인: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ -v`
