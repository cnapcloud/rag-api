---
name: known-bugs
description: 프로젝트 내 알려진 버그 및 미구현 파일 목록
metadata: 
  node_type: memory
  type: project
  originSessionId: 8d64a12e-8ccb-46d4-9977-4b334c0ec4a7
---

**infra/qdrant.py 미구현**: 현재 minio.py 코드가 그대로 복붙되어 있음. 실제 Qdrant 클라이언트 코드로 전면 교체 필요. `get_qdrant_client()`, `ensure_collection()`, `upsert_chunks()`, `delete_chunks_by_doc()`, `drop_collection()`, `search()` 함수 구현 필요.

**infra/redis.py 부분 구현**: ETag CRUD는 완성. KB 메타데이터(`register_kb`, `list_kb_ids`, `delete_kb_meta`)와 문서 상태(`get_doc_status`, `set_doc_status`, `delete_doc_meta`, `list_docs`)가 아직 없음. API 라우터가 이 함수들을 호출함.

**embed.py deprecation 경고**: line 119의 `asyncio.get_event_loop()`가 Python 3.10+에서 deprecated. `asyncio.new_event_loop()` 또는 `asyncio.run()`으로 교체 권장.

**Why:** redis.py와 qdrant.py가 minio.py 내용으로 덮어써지는 사고가 발생한 전례 있음 (2026-06-07 발견 및 redis.py 복구).

**How to apply:** infra/ 파일 수정 전 항상 내용 확인. qdrant.py 수정 시 실제 Qdrant 코드인지 확인 필수.
