# Plans

| Plan | Title | Covers | Status |
|------|-------|--------|--------|
| [01](01-mcp-server-implementation.md) | MCP Server Implementation | US-01 | done |
| [03](03-parent-child-chunking.md) | Parent-Child 청킹 & Auto-Merge 검색 | US-03 | done |
| [02](02-concurrency-guard.md) | Concurrency Guard — Sensor + QueueWorker | US-02 | done |
| [03](03-stuck-running-recovery.md) | Stuck Running Recovery — Dagster run_id check | US-05 | done |
| [04](04-zombie-detection-to-sensor.md) | Zombie Detection을 Sensor로 이동 | US-06 | todo |
| 05 | OTel Tracing — API W3C header + MCP _meta.traceparent → Langfuse | US-07 | 통합(backlog 참고) — done |
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
| 23 | Dedup Stage 1 — 해시 기반 중복 감지 | US-23 | 통합(backlog 참고) — done |
| [24](24-dedup-stage2.md) | Dedup Stage 2 — MinHash + pg_trgm | US-24 | done |
| [25](25-kiwi-user-words.md) | Kiwi 사용자 사전 파일 지원 | US-25 | done |
| [26](26-delete-pipeline-refactor.md) | Delete Pipeline Refactor — soft/hard delete 분기 + status guard | US-26 | done |
| [27](27-force-fail-api.md) | Force Fail API — 진행 중 문서 강제 실패 처리 + Dagster job terminate | US-27 | done |
| 28 | Force Delete — indexed 문서 hard delete + outdated 자동 force 처리 | US-28 | 통합(backlog 참고) — done |
| 29 | purge_doc_artifacts 공통 함수 추출 + pipeline/ops/utils/ 패키지 정리 | US-29 | 통합(backlog 참고) — done |
| [30](30-api-status-guard.md) | API Status Guard — 활성 상태 문서 upload/delete/reindex 차단 | US-30 | done |
| [31](31-admin-ui-status-guard.md) | Admin UI Status Guard — proactive 체크 + 409 에러 토스트 | US-31 | done |
| [32](32-connector-schedule-hot-reload.md) | Connector Schedule Hot Reload | US-32 | done |
| 33 | Connector Config Numeric Field Validation | US-33 | 통합(backlog 참고) — done |
| 34 | Connector Abort/Delete Guard가 QUEUED/STARTING Dagster Run을 놓치는 버그 | US-34 | 통합(backlog 참고) — done |
| 35 | Dedup Stage 3 — 청크 단위 임베딩 비교 (chunk_compare) | US-35 | 통합(backlog 참고) — done |
| 36 | HTMLCleanReader를 trafilatura 밀도 기반 추출로 교체 | US-36 | 통합(backlog 참고) — done |
| 37 | WebConnector — unrestricted 도메인 스코프 옵션 (백엔드) | US-37 | 통합(backlog 참고) — done |
| 38 | WebConnector Admin UI — seed page 포함 / unrestricted 체크박스 노출 | US-38 | 통합(backlog 참고) — done |
| 39 | HTML 추출 정책(strict/lenient/balanced) 설정화 + 기본값 lenient 전환 | US-39 | 통합(backlog 참고) — done |
| 41 | 파서 확장 레지스트리 (parse_op 확장자->리더 매핑을 등록 기반으로 전환) | US-41 | 통합(backlog 참고) — done |
| 42 | 파서 패키지 구조화 + 신규 포맷 8종 지원 (CSV/TSV/JSON/EPUB/XLSX/XLS/RST/EML) | US-42 | 통합(backlog 참고) — done |
| 43 | 레거시 .doc/.ppt + .pptx 지원 추가 | US-43 | 통합(backlog 참고) — done |
| 44 | KB별 설정 오버라이드 (ingestion/chunking/dedup) | US-44 | 통합(backlog 참고) — done |
| 45 | KB 설정 오버라이드 필드 스키마 — 값 검증/description/override 메타데이터 + `/settings/schema` | US-45 | 통합(backlog 참고) — done |
| [46](46-rest-mcp-tracing-structure-unification.md) | REST/MCP 트레이싱 구조 통일 — root span + business span(input/output) 표준화 | US-46 | in-progress |
| [47](47-page-label-type-mismatch-500.md) | 다중 KB 검색 시 page_label 타입 불일치로 인한 500 에러 수정 | US-47 | done |
| 48 | trafilatura favor_recall 모드가 인라인 서식 태그 주변 텍스트를 유실하는 버그 수정 | US-48 | 통합(backlog 참고) — done |
| 49 | chunk_overlap - chunk_size cross-field 검증 추가 | US-49 | 통합(backlog 참고) — done |
