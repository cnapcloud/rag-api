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
| 2026-07-14 | [web-connector.md](web-connector.md) | Web 커넥터 크롤링/변경 감지/추출 상호작용 및 알려진 한계 |
| 2026-07-15 | [parser-registry.md](parser-registry.md) | 파서 확장 레지스트리 — 등록 기반으로 파서 추가/교체/제거를 가능하게 하는 구조 |
| 2026-07-16 | [settings-composition.md](settings-composition.md) | Settings 확장 아키텍처 — vendoring 앱이 Settings를 안전하게 확장/공유하는 기본 설계 |
| 2026-07-18 | [kb-settings-override.md](kb-settings-override.md) | KB별 설정 오버라이드 — ingestion/chunking/dedup 값을 KB 단위로 오버라이드하는 리졸버·저장 스키마·파서 레지스트리 재설계·REST API |
| 2026-07-19 | [kb-settings-override-schema.md](kb-settings-override-schema.md) | KB 설정 오버라이드 필드 스키마 설계 — 전체 속성 min/max·enum·override 메타데이터, `/settings/schema` 엔드포인트 (kb-settings-override.md는 별도 유지, 미갱신) |
| 2026-07-29 | [parent-child-chunking.md](parent-child-chunking.md) | Parent-child 청킹 & Auto-Merge 검색 — HierarchicalNodeParser N-level 분할 + 커스텀 재귀 merge 로직(LlamaIndex AutoMergingRetriever 미사용), 자기참조 `parent_chunks` 트리 스키마, 삭제 처리, 예시 포함 |

## 변경 이력

- 2026-07-12: 여러 주제를 한 파일에 몰아 담았던 `backend.md`(2026-06-10 작성)를 해체.
  겹치는 내용은 `data-schema.md`/`doc-state-flow.md`/`system-flows.md`로 흡수하고,
  나머지는 `dagster-internals.md` / `http-error-codes.md` / `llamaindex-integration.md`로
  주제별 분리했다.
- 2026-07-12: `system-flows.md`를 `docs/internal/architecture/runtime.md`로 이동 (PRD 미대응
  순수 기술 문서이자 architecture.md와 상호 참조가 강해 아키텍처 폴더로 통합). application.md/
  technical.md는 정적 구조·인프라, runtime.md는 동적 런타임 뷰로 성격이 달라 별도 파일명 사용.
