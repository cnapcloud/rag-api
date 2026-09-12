# Specs Index

`.claude/backlogs/`+`plans/`에 있던 US-01~52를 이 인덱스 아래로 이관했다 (각 항목
`backlogs/US-NN-*.md` → `specs/US-NN-*/spec.md`, 대응하는 `plans/*.md`가 있으면
`specs/US-NN-*/plan.md`로 통합, 없으면 원래도 "통합(backlog 참고)"라 plan.md 없음).
`backlogs/spec.md`·`plans/plan.md` 인덱스 자체는 이관 완료 표시만 남기고 더 이상
갱신하지 않는다 — 이제부터는 이 파일이 유일한 인덱스다.

## 마지막 채번 번호

**US-52**

`/spec-new`가 새 번호를 줄 때 이 값 + 1을 쓰고, 쓰자마자 이 줄도 그 번호로 갱신한다.
"진행 중" 표는 완료되면 History로 옮겨져 비어 있을 수 있으므로, 다음 번호는 표를
스캔해서 구하지 말고 반드시 이 필드 하나만 보고 정한다.

## 진행 중

`/spec-new`로 항목이 생성되면 여기 한 줄 추가된다(status: todo). validator가 완료 기준을
전부 확인해 backlog **상태**를 `done`으로 바꾸는 순간, 이 표에서 지우고 아래 History로
그 행을 옮긴다. 즉 이 표에는 항상 아직 안 끝난 spec만 남는다.

| Spec | Title | Status |
|------|-------|--------|

## History

완료된 spec만 여기 쌓인다. 최근 항목이 위로 오게 추가한다.

> 아래 US-01~52 이관분은 옛 `backlogs/spec.md`에 완료 날짜가 없어 "Completed"에
> 실제 날짜를 채우지 못했다 — US 번호 내림차순(번호가 클수록 최근)을 실제 완료 순서의
> 근사치로 대신 사용한다. US-53 이후 신규 항목부터는 validator가 `done` 전환 시점의
> 실제 날짜를 기록한다.

| Spec | Title | Completed |
|------|-------|-----------|
| [US-52](US-52-batch-upload-failure-status-and-error-surfacing/spec.md) | 배치 문서 업로드 실패 시 HTTP 상태 코드 정합성 + 실패 사유 노출 | (이관, 날짜 미상) |
| [US-51](US-51-pipeline-hooks-before-doc-create/spec.md) | 파이프라인 훅 — 신규 문서 생성 직전 등록 기반 콜백(BeforeDocCreate/HookAbort/emit) | (이관, 날짜 미상) |
| [US-50](US-50-provider-openai-compat-generalization/spec.md) | 임베딩 provider 일반화 — 프로토콜 커넥션 + 미지 벤더 OpenAI 호환 폴백 + Jina 네이티브 | (이관, 날짜 미상) |
| [US-49](US-49-chunk-overlap-validation/spec.md) | chunk_overlap - chunk_size cross-field 검증 추가 | (이관, 날짜 미상) |
| [US-48](US-48-html-trafilatura-inline-tag-text-loss/spec.md) | trafilatura favor_recall 모드가 인라인 서식 태그 주변 텍스트를 유실하는 버그 수정 | (이관, 날짜 미상) |
| [US-47](US-47-page-label-type-mismatch-500/spec.md) | 다중 KB 검색 시 page_label 타입 불일치로 인한 500 에러 수정 | (이관, 날짜 미상) |
| [US-45](US-45-kb-settings-field-schema/spec.md) | KB 설정 오버라이드 필드 스키마 — 값 검증/description/override 메타데이터 + `/settings/schema` | (이관, 날짜 미상) |
| [US-44](US-44-kb-settings-override/spec.md) | KB별 설정 오버라이드 (ingestion/chunking/dedup) | (이관, 날짜 미상) |
| [US-43](US-43-legacy-office-formats/spec.md) | 레거시 .doc/.ppt + .pptx 지원 추가 | (이관, 날짜 미상) |
| [US-42](US-42-parser-package-restructure/spec.md) | 파서 패키지 구조화 + 신규 포맷 8종 지원 (CSV/TSV/JSON/EPUB/XLSX/XLS/RST/EML) | (이관, 날짜 미상) |
| [US-41](US-41-parser-extension-registry/spec.md) | 파서 확장 레지스트리 (parse_op 확장자->리더 매핑을 등록 기반으로 전환) | (이관, 날짜 미상) |
| [US-39](US-39-html-extraction-policy-lenient-default/spec.md) | HTML 추출 정책(strict/lenient/balanced) 설정화 + 기본값 lenient 전환 | (이관, 날짜 미상) |
| [US-38](US-38-web-connector-admin-ui-unrestricted/spec.md) | WebConnector Admin UI — seed page 포함 / unrestricted 체크박스 노출 | (이관, 날짜 미상) |
| [US-37](US-37-web-connector-unrestricted-scope/spec.md) | WebConnector — unrestricted 도메인 스코프 옵션 (백엔드) | (이관, 날짜 미상) |
| [US-36](US-36-html-trafilatura-extraction/spec.md) | HTMLCleanReader를 trafilatura 밀도 기반 추출로 교체 | (이관, 날짜 미상) |
| [US-35](US-35-dedup-stage3-chunk-compare/spec.md) | Dedup Stage 3 — 청크 단위 임베딩 비교(chunk_compare) + 임계값 기반 body 확정 | (이관, 날짜 미상) |
| [US-34](US-34-connector-abort-missed-queued-run/spec.md) | Connector Abort/Delete Guard가 QUEUED/STARTING Dagster Run을 놓치는 버그 | (이관, 날짜 미상) |
| [US-33](US-33-connector-config-validation/spec.md) | Connector Config Numeric Field Validation — type/range 검증 + min_content_chars settings 이전 | (이관, 날짜 미상) |
| [US-32](US-32-connector-schedule-hot-reload/spec.md) | Connector Schedule Hot Reload via Dagster Code Location Reload | (이관, 날짜 미상) |
| [US-31](US-31-admin-ui-status-guard/spec.md) | Admin UI Status Guard — proactive 체크 + 409 에러 토스트 (rag-admin) | (이관, 날짜 미상) |
| [US-30](US-30-api-status-guard/spec.md) | API Status Guard — 활성 상태 문서 upload/delete/reindex 차단 | (이관, 날짜 미상) |
| [US-29](US-29-purge-doc-artifacts/spec.md) | purge_doc_artifacts 공통 함수 추출 — Qdrant/S3/dedup 밴드 정리 통합 | (이관, 날짜 미상) |
| [US-28](US-28-force-delete/spec.md) | Force Delete — indexed 문서 hard delete + outdated 자동 force 처리 | (이관, 날짜 미상) |
| [US-27](US-27-force-fail-api/spec.md) | Force Fail API — 진행 중 문서 강제 실패 처리 + Dagster job terminate | (이관, 날짜 미상) |
| [US-26](US-26-delete-pipeline-refactor/spec.md) | Delete Pipeline Refactor — soft/hard delete 분기 + status guard | (이관, 날짜 미상) |
| [US-25](US-25-kiwi-user-words/spec.md) | Kiwi 형태소 분석기 사용자 사전 파일 지원 | (이관, 날짜 미상) |
| [US-24](US-24-dedup-stage2/spec.md) | Dedup Stage 2 — MinHash Jaccard + pg_trgm 제목 퍼지 필터링 | (이관, 날짜 미상) |
| [US-23](US-23-dedup-stage1/spec.md) | Dedup Stage 1 — 해시 기반 중복 감지 (SimHash + SHA-256) | (이관, 날짜 미상) |
| [US-22](US-22-discard-ingest-on-deleting/spec.md) | deleting 상태 문서의 ingest/delete 이벤트 즉시 버림 | (이관, 날짜 미상) |
| [US-21](US-21-github-connector/spec.md) | GitHubConnector implementation (R-11) | (이관, 날짜 미상) |
| [US-20](US-20-confluence-connector/spec.md) | ConfluenceConnector implementation (R-10) | (이관, 날짜 미상) |
| [US-19](US-19-connector-dagster-schedule/spec.md) | Connector Dagster Schedule dynamic registration (R-12) | (이관, 날짜 미상) |
| [US-18](US-18-web-connector/spec.md) | WebConnector implementation (R-09) | (이관, 날짜 미상) |
| [US-17](US-17-html-clean-reader/spec.md) | parse_op HTML clean reader — strip nav/footer/script (R-08) | (이관, 날짜 미상) |
| [US-16](US-16-connector-crud-sync-api/spec.md) | Connector CRUD + Sync API (R-06, R-07) | (이관, 날짜 미상) |
| [US-15](US-15-multi-source-schema-init/spec.md) | Multi-source ingest schema initialization (R-01) | (이관, 날짜 미상) |
| [US-14](US-14-pending-status/spec.md) | pending 상태 구현 — 큐 대기 상태 가시성 확보 | (이관, 날짜 미상) |
| [US-13](US-13-doc-list-api-pagination-search-sort/spec.md) | Document List API — 페이지네이션 / 검색 / 정렬 | (이관, 날짜 미상) |
| [US-11](US-11-postgres-schema-migration/spec.md) | Postgres 스키마 설계 및 Redis 메타데이터 이전 | (이관, 날짜 미상) |
| [US-10](US-10-doc-created-at/spec.md) | 문서 생성일자 메타데이터 저장 및 reindex 큐 정렬 | (이관, 날짜 미상) |
| [US-08](US-08-min-score-filter/spec.md) | 검색 모드 분리 및 유사도 기반 필터 (min_score threshold) | (이관, 날짜 미상) |
| [US-07](US-07-mcp-otel-tracing/spec.md) | OpenTelemetry 트레이싱 — MCP _meta.traceparent → Langfuse | (이관, 날짜 미상) |
| [US-05](US-05-stuck-running-recovery/spec.md) | Stuck Running 자동 복구 (서버 재시작 시 zombie 상태 해소) | (이관, 날짜 미상) |
| [US-03](US-03-parent-child-chunking/spec.md) | Parent-Child 청킹 & Auto-Merge 검색 | (이관, 날짜 미상) |
| [US-02](US-02-concurrency-guard/spec.md) | Delete/Ingest 동시 실행 경쟁 조건 해결 | (이관, 날짜 미상) |
| [US-01](US-01-mcp-server/spec.md) | MCP 서버 | (이관, 날짜 미상) |
