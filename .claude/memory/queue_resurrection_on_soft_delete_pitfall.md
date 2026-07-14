---
name: queue-resurrection-on-soft-delete-pitfall
description: connector/KB 삭제 시 남아있던 Redis ingest 이벤트가 이미 삭제된 문서를 되살려 영구히 404 재시도하던 문제 (2026-07-14)
metadata:
  type: feedback
---

`_cascade_delete`(커넥터 삭제)와 `delete_kb`는 문서의 S3/Qdrant 콘텐츠를 지우기 전에 그 문서의
"살아있는" ingest 이벤트(`rag:upload:queue` 메인 큐 + `rag:upload:delay` 재시도 대기열)를 먼저
제거하지 않았다. `event_queue_sensor`의 `_drain_delay_queue()`는 `running`/`deleting` 상태만
예외 처리하고 `deleted`는 걸러내지 않아서, delay queue에 남아있던 이벤트가 나중에 드레인되며
이미 soft-delete된 문서를 `pending`으로 되살렸다. 되살아난 문서는 `validate_op`은 통과하지만
`parse_op`이 이미 지워진 S3 storage_key를 받아오려다 매번 404로 실패 — 재시도해도 원본이
없으므로 영원히 실패한다.

**Why:** `kb-01`의 namu.wiki 웹 커넥터를 삭제한 뒤, doc_id `48443aa190e94c39`("물소") 하나만
이전 실행이 delay queue에 걸려있던 상태였고, 커넥터 삭제 후 몇 시간 뒤 드레인되며 부활 →
`ingest_job`이 3번 연속 `HeadObject 404`로 실패하는 것을 Dagster Run 화면에서 확인.

**How to apply:** 문서를 가리키는 상위 리소스(KB, connector)를 지우거나 sync를 abort할 때는,
실제 콘텐츠(S3/Qdrant)를 지우기 *전에* 그 리소스에 속한 pending/running 문서의 큐 이벤트를
먼저 정리해야 한다. 이 정리는
[`pipeline/utils/abort_ingest.py::abort_active_ingest()`](../../src/rag_api/pipeline/utils/abort_ingest.py)로
공통화되어 있다 — 새로운 삭제/중단 경로를 추가할 때는 반드시 이 함수를 재사용할 것, 직접
`soft_delete_doc`/`hard_delete_doc`부터 부르지 말 것. `abort_active_ingest`는 pending과
running 둘 다 `dequeue_upload_events()`로 큐에서 제거한다 — running만 처리하고 delay queue에
남은 과거 재시도 이벤트를 놓치는 실수(기존 `abort_sync` 초기 구현의 버그였음)에 주의.

KB 삭제는 `documents.kb_id` FK가 `ON DELETE CASCADE`라 문서 row 자체가 사라지므로, 이 레이스가
나도 "Document not found"로 자연 종료되고 흔적이 안 남는다 — 그래서 validate() 레벨 가드는
불필요하다고 판단, 큐 정리만으로 충분. 반면 `documents.connector_id` FK는
`ON DELETE SET NULL`이라 문서 row가 soft-delete 상태로 영구히 남는다 — 이 케이스가 실제
장애를 일으켰다.
