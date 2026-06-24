# Backlog

| ID | Title | Status |
|----|-------|--------|
| [US-01](US-01-mcp-server.md) | MCP 서버 | done |
| [US-02](US-02-concurrency-guard.md) | Delete/Ingest 동시 실행 경쟁 조건 해결 | done |
| [US-03](todo/US-03-small-to-big-retrieval.md) | Small-to-Big Retrieval (document_aware 계층 검색) | todo |
| [US-04](todo/US-04-image-handling.md) | 문서 이미지 캡셔닝 (parse_op vision 처리) | todo |
| [US-05](US-05-stuck-running-recovery.md) | Stuck Running 자동 복구 (서버 재시작 시 zombie 상태 해소) | done |
| [US-06](US-06-sensor-dispatch-lock-false-zombie.md) | Sensor dispatch lock이 zombie로 오탐되는 버그 | todo |
| [US-07](US-07-mcp-otel-tracing.md) | OpenTelemetry 트레이싱 — MCP _meta.traceparent → Langfuse | done |
| [US-08](US-08-min-score-filter.md) | 검색 모드 분리 및 유사도 기반 필터 (min_score threshold) | done |
| [US-10](US-10-doc-created-at.md) | 문서 생성일자 메타데이터 저장 및 reindex 큐 정렬 | done |
| [US-11](US-11-postgres-schema-migration.md) | Postgres 스키마 설계 및 Redis 메타데이터 이전 | done |
| [US-13](US-13-doc-list-api-pagination-search-sort.md) | Document List API — 페이지네이션 / 검색 / 정렬 | done |
| [US-14](US-14-pending-status.md) | pending 상태 구현 — 큐 대기 상태 가시성 확보 | done |
| [US-15](US-15-multi-source-schema-init.md) | Multi-source ingest schema initialization (R-01) | done |
| [US-16](US-16-connector-crud-sync-api.md) | Connector CRUD + Sync API (R-06, R-07) | done |
| [US-17](US-17-html-clean-reader.md) | parse_op HTML clean reader — strip nav/footer/script (R-08) | done |
| [US-18](US-18-web-connector.md) | WebConnector implementation (R-09) | done |
| [US-19](US-19-connector-dagster-schedule.md) | Connector Dagster Schedule dynamic registration (R-12) | done |
