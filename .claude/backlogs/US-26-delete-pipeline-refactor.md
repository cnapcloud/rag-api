---
id: US-26
title: Delete Pipeline Refactor — soft/hard delete 분기 + status guard
status: done
---

## 배경

현재 delete pipeline은 status에 관계없이 항상 동일하게 동작한다:
- Qdrant 청크 삭제
- S3 삭제 (indexed 문서도 S3를 지워버리는 버그 포함)
- DB soft delete

또한 `runner.py`와 `delete_ops.py`(3개 op)가 동일 로직을 중복 구현하고 있으며,
`deleting` 중복 요청에 대한 방어도 없다.

## 목표

1. **status 기반 분기**: indexed → soft delete / 그 외 → hard delete
2. **API 레이어 status guard**: running/deleting/deleted 요청 시 409 반환
3. **순수 함수 통합**: `pipeline/ops/delete.py::delete_doc()` 로 로직 일원화
4. **Dagster op 단순화**: 3개 op → 1개 op

## 수용 기준

- `indexed` 문서 삭제: Qdrant 청크 삭제 + DB status='deleted' + S3 유지
- `outdated/failed/pending` 등 삭제: Qdrant 청크 삭제 시도 + S3 삭제 + DB row hard delete (CASCADE → bands 자동 정리)
- `running` 상태 삭제 요청 → 409 "currently being processed, try again later"
- `deleting` 상태 삭제 요청 → 409 "already being deleted"
- `deleted` 상태 삭제 요청 → 허용 (hard delete 경로 진행)
- `delete_doc()` 내부에서 `deleting` 재진입 시 early return (2차 방어, `deleted`는 통과)
- `runner.py`와 `delete_op`(Dagster) 양쪽 모두 `delete_doc()` 호출로 교체
- delay queue (running 대기) 로직은 그대로 유지
