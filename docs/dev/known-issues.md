# Known Issues

발견된 이슈를 기록하는 문서. 해결 시 상태를 `open` -> `resolved`로 변경하고 해결 방법을 기록한다.

---

## 목차

1. [DELETE /docs/{source} returns 200 for non-existent document](#1-delete-docssource-returns-200-for-non-existent-document)
2. [Dagster SensorDefinition owners parameter BetaWarning](#2-dagster-sensordefinition-owners-parameter-betawarning)

---

## 1. DELETE /docs/{source} returns 200 for non-existent document

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-06-19 |
| 심각도 | LOW |

**증상**

존재하지 않는 문서를 삭제 요청해도 `200 {"status":"deleted"}`가 반환된다.

```bash
curl -X DELETE http://localhost:8000/api/kb/kb-01/docs/notexist.pdf
# {"kb_id":"kb-01","doc_source":"notexist.pdf","status":"deleted"}  HTTP 200
```

**원인**

`DELETE /api/kb/{kb_id}/docs/{source}` 라우터가 삭제 전 문서 존재 여부를 확인하지 않는다.
Qdrant 및 Redis에서 해당 키가 없더라도 삭제 연산 자체는 오류 없이 완료되므로
결과적으로 아무것도 삭제하지 않았음에도 성공 응답을 반환한다.

**기대 동작**

문서가 존재하지 않으면 `404 NotFoundError`를 반환해야 한다.

**해결 방안**

삭제 로직 전에 Redis에서 문서 메타데이터 존재 여부를 조회하고,
없으면 `NotFoundError`를 raise한다.

```python
# api/routers/docs.py
meta = get_doc_meta(kb_id, source)
if meta is None:
    raise NotFoundError(f"Document not found: kb={kb_id} source={source}")
```

**비고**

REST 표준(RFC 9110)상 DELETE는 멱등(idempotent)이어야 하지만,
두 번째 호출이 404를 반환하는 것은 허용된다.
클라이언트가 실제 삭제 여부를 구분할 수 없는 현 동작은 혼란을 유발할 수 있다.

---

## 2. Dagster SensorDefinition owners parameter BetaWarning

| 항목 | 내용 |
|------|------|
| 상태 | open |
| 발견일 | 2026-06-19 |
| 심각도 | LOW |

**증상**

Dagster daemon 시작 시 아래 경고가 출력된다.

```
/usr/local/lib/python3.12/site-packages/dagster/_core/definitions/sensor_definition.py:809:
BetaWarning: Parameter `owners` of initializer `SensorDefinition.__init__` is currently
in beta, and may have breaking changes in minor version releases, with behavior changes
in patch releases.
```

**원인**

`SensorDefinition` (또는 `@sensor` 데코레이터) 초기화 시 `owners` 파라미터를 전달하고 있으나,
해당 파라미터가 Dagster 1.7에서 아직 베타 상태다.

**해결 방안**

Option A — `owners` 파라미터 제거:

센서 정의에서 `owners=[...]` 인자를 삭제한다. 소유자 정보가 필요하지 않다면 가장 간단한 해결책.

Option B — 경고 억제 (임시방편):

```python
import warnings
from dagster import BetaWarning
warnings.filterwarnings("ignore", category=BetaWarning)
```

**비고**

Dagster가 `owners` 파라미터를 정식 릴리스하면 경고는 자동으로 사라진다.
현재 기능 동작에는 영향 없음.
