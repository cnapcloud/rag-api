---
name: qdrant-ensure-collection-bare-except-pitfall
description: ensure_collection의 bare except Exception이 404 아닌 에러까지 삼켜서 이미 존재하는 컬렉션에 create_collection을 호출, 409 Conflict 유발 (2026-07-13)
metadata:
  type: feedback
---

`infra/qdrant.py`의 `ensure_collection()`에서 `c.get_collection(kb_id)` 실패를 `except
Exception: pass`로 뭉뚱그려 처리하면 안 된다. "컬렉션이 정말 없어서(404)" 난 예외와 그 외 예외
(네트워크 지연, 일시적 5xx 등)를 구분하지 않으면, 컬렉션이 실제로 존재하는 상태에서 다른 이유로
`get_collection`이 실패했을 때도 "없음"으로 오판해 바로 아래 `c.create_collection(...)`을
호출하게 되고, 서버가 `409 Conflict: Collection already exists`를 던진다. Dagster
`upsert_op` 스택트레이스는 이 409를 최상위 원인처럼 보여주지만 실제 버그는 그 이전 단계인
`get_collection` 예외 처리 쪽에 있었다.

**Why:** 운영 중 `upsert_op`이 `kb-01`에 대해 409로 실패. 원인 추적 결과 `except Exception:
pass`가 진짜 원인(get_collection이 404 아닌 다른 이유로 실패)을 감추고 있었음.

**How to apply:** `qdrant_client.http.exceptions.UnexpectedResponse`를 잡아서
`status_code == 404`일 때만 "생성 필요"로 넘어가고, 그 외에는 반드시 재전파한다. 이런 "존재
확인 → 없으면 생성" 패턴을 다른 infra 함수에 새로 만들 때도 동일하게 바른 예외 타입/코드로
분기할 것 — bare `except Exception: pass`로 "리소스 없음"을 판별하지 말 것.
회귀 테스트: `tests/unit/test_qdrant_infra.py`.
