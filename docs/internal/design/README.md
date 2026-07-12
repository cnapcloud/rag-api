# Design 문서 인덱스

`docs/internal/design/`의 설계 문서 목록. 생성일 순(오래된 순)으로 정렬했다.
요건과의 연결은 [prd.md](../requirement/prd.md), 시스템 전체 구조는 [architecture/README.md](../architecture/README.md) 참조.
런타임 처리 흐름은 [architecture/runtime.md](../architecture/runtime.md)로 이동했다.

| 생성일 | 문서 | 설명 |
|--------|------|------|
| 2026-06-10 | [http-error-codes.md](http-error-codes.md) | 예외 클래스 -> HTTP status 매핑 |
| 2026-06-10 | [dagster-internals.md](dagster-internals.md) | Dagster sensor/op 내부 동작 원리 |
| 2026-06-10 | [llamaindex-integration.md](llamaindex-integration.md) | LlamaIndex 파싱/청킹/임베딩/검색 활용 범위 |
| 2026-06-19 | [data-schema.md](data-schema.md) | Qdrant payload, Postgres 테이블, Redis 큐 키 구조 |
| 2026-06-19 | [dedup.md](dedup.md) | 중복 감지 파이프라인 상세 설계 |
| 2026-06-20 | [frontend.md](frontend.md) | 프론트엔드(Admin UI) 설계 |
| 2026-06-22 | [mcp.md](mcp.md) | MCP 서버 설계 |
| 2026-06-24 | [multi-source-ingest.md](multi-source-ingest.md) | 멀티소스(커넥터) 인제스트 흐름/스키마 재설계 |
| 2026-06-28 | [doc-status-guard.md](doc-status-guard.md) | upload/delete/reindex API의 활성 상태 기반 차단 정책 |
| 2026-06-28 | [connector-state-flow.md](connector-state-flow.md) | 커넥터 상태(status/sync_status) 흐름과 API 관계 |
| 2026-06-28 | [doc-state-flow.md](doc-state-flow.md) | 문서 상태 전이 및 API별 허용 조건 |
| 2026-07-04 | [duplicate-request-handling.md](duplicate-request-handling.md) | 큐 dedup / 중복 dispatch 처리 |
| 2026-07-09 | [html-extraction.md](html-extraction.md) | HTML 본문 추출 설계 |

## 변경 이력

- 2026-07-12: 여러 주제를 한 파일에 몰아 담았던 `backend.md`(2026-06-10 작성)를 해체.
  겹치는 내용은 `data-schema.md`/`doc-state-flow.md`/`system-flows.md`로 흡수하고,
  나머지는 `dagster-internals.md` / `http-error-codes.md` / `llamaindex-integration.md`로
  주제별 분리했다.
- 2026-07-12: `system-flows.md`를 `docs/internal/architecture/runtime.md`로 이동 (PRD 미대응
  순수 기술 문서이자 architecture.md와 상호 참조가 강해 아키텍처 폴더로 통합). application.md/
  technical.md는 정적 구조·인프라, runtime.md는 동적 런타임 뷰로 성격이 달라 별도 파일명 사용.
