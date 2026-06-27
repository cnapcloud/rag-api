# Plans

| Plan | Title | Covers | Status |
|------|-------|--------|--------|
| [01](01-mcp-server-implementation.md) | MCP Server Implementation | US-01 | done |
| [02](02-concurrency-guard.md) | Concurrency Guard — Sensor + QueueWorker | US-02 | done |
| [03](03-stuck-running-recovery.md) | Stuck Running Recovery — Dagster run_id check | US-05 | done |
| [04](04-zombie-detection-to-sensor.md) | Zombie Detection을 Sensor로 이동 | US-06 | todo |
| [05](05-otel-tracing.md) | OTel Tracing — API W3C header + MCP _meta.traceparent → Langfuse | US-07 | todo |
| [08](08-search-mode-split-min-score.md) | 검색 모드 분리 및 유사도 기반 필터 (hybrid / similarity) | US-08 | done |
| [11](11-postgres-schema-migration.md) | Postgres 스키마 설계 및 Redis 메타데이터 이전 | US-11 | done |
| [13](13-doc-list-pagination.md) | Document List API — 페이지네이션 / 검색 / 정렬 | US-13 | done |
| [14](14-pending-status.md) | pending 상태 구현 — 큐 대기 상태 가시성 확보 | US-14 | done |
| [15](15-multi-source-schema-init.md) | Multi-source ingest schema initialization | US-15 | done |
| [16](16-connector-crud-sync-api.md) | Connector CRUD + Sync API | US-16 | done |
| [17](17-html-clean-reader.md) | HTML Clean Reader — strip nav/footer/script (R-08) | US-17 | done |
| [18](18-web-connector.md) | WebConnector implementation (R-09) | US-18 | done |
| [19](19-connector-dagster-schedule.md) | Connector Dagster Schedule dynamic registration (R-12) | US-19 | done |
| [20](20-confluence-connector.md) | ConfluenceConnector implementation (R-10) | US-20 | done |
| [21](21-github-connector.md) | GitHubConnector implementation (R-11) | US-21 | done |
| [22](22-discard-ingest-on-deleting.md) | deleting 상태 이벤트 즉시 버림 | US-22 | done |
| [24](24-dedup-stage2.md) | Dedup Stage 2 — MinHash + pg_trgm | US-24 | done |
| [25](25-kiwi-user-words.md) | Kiwi 사용자 사전 파일 지원 | US-25 | done |
