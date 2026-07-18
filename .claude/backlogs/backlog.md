# Backlog

> 포맷 마이그레이션(`.claude/rules/conventions/07-traceability.md`, 2026-07-12 도입): `_TEMPLATE.md`
> 형식(`> 설계:` 링크 포함)으로 전환 완료된 항목은 US-23/24/35뿐. 나머지는 구 형식 유지 —
> 해당 항목을 실제로 다시 열어 작업할 때 opportunistic하게 전환한다. 일괄 전환 작업은 계획하지 않음.

| ID | Title | Status |
|----|-------|--------|
| [US-01](US-01-mcp-server.md) | MCP 서버 | done |
| [US-02](US-02-concurrency-guard.md) | Delete/Ingest 동시 실행 경쟁 조건 해결 | done |
| [US-03](todo/US-03-small-to-big-retrieval.md) | Small-to-Big Retrieval (document_aware 계층 검색) | todo |
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
| [US-20](US-20-confluence-connector.md) | ConfluenceConnector implementation (R-10) | done |
| [US-21](US-21-github-connector.md) | GitHubConnector implementation (R-11) | done |
| [US-22](US-22-discard-ingest-on-deleting.md) | deleting 상태 문서의 ingest/delete 이벤트 즉시 버림 | done |
| [US-23](US-23-dedup-stage1.md) | Dedup Stage 1 — 해시 기반 중복 감지 (SimHash + SHA-256) | done |
| [US-24](US-24-dedup-stage2.md) | Dedup Stage 2 — MinHash Jaccard + pg_trgm 제목 퍼지 필터링 | done |
| [US-25](US-25-kiwi-user-words.md) | Kiwi 형태소 분석기 사용자 사전 파일 지원 | done |
| [US-26](US-26-delete-pipeline-refactor.md) | Delete Pipeline Refactor — soft/hard delete 분기 + status guard | done |
| [US-27](US-27-force-fail-api.md) | Force Fail API — 진행 중 문서 강제 실패 처리 + Dagster job terminate | done |
| [US-28](US-28-force-delete.md) | Force Delete — indexed 문서 hard delete + outdated 자동 force 처리 | done |
| [US-29](US-29-purge-doc-artifacts.md) | purge_doc_artifacts 공통 함수 추출 — Qdrant/S3/dedup 밴드 정리 통합 | done |
| [US-30](US-30-api-status-guard.md) | API Status Guard — 활성 상태 문서 upload/delete/reindex 차단 | done |
| [US-31](US-31-admin-ui-status-guard.md) | Admin UI Status Guard — proactive 체크 + 409 에러 토스트 (rag-admin) | done |
| [US-32](US-32-connector-schedule-hot-reload.md) | Connector Schedule Hot Reload via Dagster Code Location Reload | done |
| [US-33](US-33-connector-config-validation.md) | Connector Config Numeric Field Validation — type/range 검증 + min_content_chars settings 이전 | done |
| [US-34](US-34-connector-abort-missed-queued-run.md) | Connector Abort/Delete Guard가 QUEUED/STARTING Dagster Run을 놓치는 버그 | done |
| [US-35](US-35-dedup-stage3-chunk-compare.md) | Dedup Stage 3 — 청크 단위 임베딩 비교(chunk_compare) + 임계값 기반 body 확정 | done |
| [US-36](US-36-html-trafilatura-extraction.md) | HTMLCleanReader를 trafilatura 밀도 기반 추출로 교체 | done |
| [US-37](US-37-web-connector-unrestricted-scope.md) | WebConnector — unrestricted 도메인 스코프 옵션 (백엔드) | done |
| [US-38](US-38-web-connector-admin-ui-unrestricted.md) | WebConnector Admin UI — seed page 포함 / unrestricted 체크박스 노출 | done |
| [US-39](US-39-html-extraction-policy-lenient-default.md) | HTML 추출 정책(strict/lenient/balanced) 설정화 + 기본값 lenient 전환 | done |
| [US-41](US-41-parser-extension-registry.md) | 파서 확장 레지스트리 (parse_op 확장자->리더 매핑을 등록 기반으로 전환) | done |
| [US-42](US-42-parser-package-restructure.md) | 파서 패키지 구조화 + 신규 포맷 8종 지원 (CSV/TSV/JSON/EPUB/XLSX/XLS/RST/EML) | done |
| [US-43](US-43-legacy-office-formats.md) | 레거시 .doc/.ppt + .pptx 지원 추가 | done |
| [US-44](US-44-kb-settings-override.md) | KB별 설정 오버라이드 (ingestion/chunking/dedup) | done |
