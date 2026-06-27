# Test Catalog

전체 테스트 목록 및 검증 내용 정리. 124개 수집 기준.

실행 명령:
```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ -v
PYTHONPATH=src .venv/bin/python -m pytest tests/dagster/ -v
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/ -v
```

---

## 1. Unit — Chunking (`tests/unit/test_chunk.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_chunk_recursive_splits_long_text` | 긴 텍스트가 여러 청크로 분할되는지 |
| `test_chunk_adds_metadata` | 청크에 메타데이터(kb_id, doc_source 등)가 포함되는지 |
| `test_chunk_document_aware_returns_leaf_nodes` | document_aware 전략이 leaf 노드를 반환하는지 (SKIP: 대용량 모델 필요) |
| `test_chunk_single_short_document` | 짧은 문서는 단일 청크로 처리되는지 |

---

## 2. Unit — 문서 생성일자 (`tests/unit/test_doc_created_at.py`)

US-10 구현 검증.

### TestExtractDocCreatedAt

| Test | 검증 내용 |
|------|-----------|
| `test_pdf_creation_date` | PDF CreationDate 메타데이터 추출 |
| `test_pdf_no_creation_date_falls_back_to_s3` | PDF에 CreationDate 없으면 S3 LastModified 폴백 |
| `test_docx_created_date` | DOCX core_properties.created 추출 |
| `test_unsupported_type_falls_back_to_s3` | 지원하지 않는 파일 형식은 S3 LastModified 폴백 |
| `test_s3_fallback_failure_returns_empty` | S3 폴백도 실패하면 빈 문자열 반환 |
| `test_naive_datetime_coerced_to_utc` | timezone-naive datetime은 UTC로 처리 |

### TestUpsertDocCreatedAt

| Test | 검증 내용 |
|------|-----------|
| `test_upsert_result_carries_doc_created_at` | UpsertResult에 doc_created_at 포함 |
| `test_qdrant_payload_includes_doc_created_at` | Qdrant PointStruct payload에 doc_created_at 포함 |
| `test_empty_embedded_nodes_doc_created_at_is_empty` | 임베딩 노드 없으면 doc_created_at 빈 문자열 |

### TestMetaDocCreatedAt

| Test | 검증 내용 |
|------|-----------|
| `test_update_meta_stores_doc_created_at` | update_meta가 doc_created_at을 Postgres에 저장 |
| `test_update_meta_omits_doc_created_at_when_empty` | doc_created_at 빈 문자열이면 필드 생략 |

### TestReindexOrdering

| Test | 검증 내용 |
|------|-----------|
| `test_reindex_ordered_by_doc_created_at_from_postgres` | reindex 시 Postgres doc_created_at 기준 오래된 문서 먼저 큐잉 |
| `test_reindex_fallback_to_s3_last_modified_when_no_postgres` | Postgres 정보 없으면 S3 LastModified 기준 정렬 |

---

## 3. Unit — 문서 목록 API (`tests/unit/test_doc_list_api.py`)

US-13 구현 검증. `GET /api/kb/{id}/docs` 페이지네이션 / 검색 / 정렬.

### TestListDocsDefaultResponse

| Test | 검증 내용 |
|------|-----------|
| `test_returns_paginated_shape` | 응답에 items / total / page / page_size 포함 |
| `test_default_params_passed_to_postgres` | 기본 파라미터(page=1, page_size=20, sort=updated_at desc) 전달 |

### TestListDocsPagination

| Test | 검증 내용 |
|------|-----------|
| `test_page2_passed_correctly` | page=2 파라미터 정상 전달 |
| `test_out_of_range_page_returns_empty_items` | 범위 초과 페이지는 빈 items 반환 |
| `test_page_size_clamped_to_100` | page_size 최대값 100 제한 |
| `test_page_less_than_1_returns_422` | page < 1이면 422 |

### TestListDocsSearch

| Test | 검증 내용 |
|------|-----------|
| `test_search_param_forwarded` | search 파라미터 Postgres 함수에 전달 |
| `test_search_case_insensitive_in_store` | ILIKE 기반 대소문자 무시 검색 |

### TestListDocsStatusFilter

| Test | 검증 내용 |
|------|-----------|
| `test_status_param_forwarded` | status 파라미터 Postgres 함수에 전달 |
| `test_status_filter_in_store` | 상태 필터링 결과 정확성 |

### TestListDocsSort

| Test | 검증 내용 |
|------|-----------|
| `test_sort_by_param_forwarded` | sort_by 파라미터 전달 |
| `test_invalid_sort_by_returns_422` | 허용되지 않는 sort_by 값은 422 |
| `test_invalid_sort_order_returns_422` | 허용되지 않는 sort_order 값은 422 |
| `test_sort_by_doc_source_asc_in_store` | doc_source ASC 정렬 |
| `test_null_chunk_count_sorts_last_desc` | chunk_count NULL은 DESC 정렬 시 마지막 |
| `test_null_chunk_count_sorts_last_asc` | chunk_count NULL은 ASC 정렬 시 마지막 |

### TestListDocsItemShape

| Test | 검증 내용 |
|------|-----------|
| `test_item_fields_present` | 응답 항목에 필수 필드 (doc_source, status, etag 등) 모두 포함 |

---

## 4. Unit — 임베딩 (`tests/unit/test_embed.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_embed_returns_embedded_nodes` | embed()가 EmbeddedNode 리스트 반환 |
| `test_embed_adds_metadata` | 임베딩 노드에 dense/sparse 벡터 포함 |

---

## 5. Unit — MCP 도구 (`tests/unit/test_mcp_tools.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_list_knowledge_bases_returns_all` | list_knowledge_bases가 전체 KB 반환 |
| `test_list_knowledge_bases_empty` | KB 없으면 빈 목록 반환 |
| `test_get_document_status_indexed` | indexed 상태 문서 조회 |
| `test_get_document_status_not_found` | 없는 문서 조회 시 not_found 응답 |
| `test_get_document_status_no_size` | file_size 없는 문서도 정상 처리 |
| `test_search_with_explicit_kb_ids` | 명시적 kb_ids로 검색 |
| `test_search_expands_to_all_kbs_when_none_specified` | kb_ids 미지정 시 전체 KB 검색 |
| `test_search_returns_empty_when_no_kbs` | KB 없으면 빈 결과 반환 |

---

## 6. Unit — QueueWorker 동시성 (`tests/unit/test_queue_worker.py`)

`pipeline/queue_worker.py` — Redis 큐 소비 및 동시 처리 방어 로직.

### Poll 동작

| Test | 검증 내용 |
|------|-----------|
| `test_poll_upload_not_processing_dispatches` | upload: doc 미처리 중 → _run_ingest 디스패치 |
| `test_poll_upload_while_processing_requeues` | upload: running(run_id 있음) → _requeue_after_delay |
| `test_poll_upload_while_processing_no_run_id_requeues` | upload: running(run_id 없음, QueueWorker 모드) → _requeue_after_delay |
| `test_poll_upload_while_deleting_requeues` | upload: deleting → _requeue_after_delay |
| `test_poll_delete_not_processing_dispatches` | delete: doc 미처리 중 → _run_delete 디스패치 |
| `test_poll_delete_while_processing_requeues` | delete: running → _requeue_after_delay |
| `test_poll_delete_while_deleting_requeues` | delete: deleting → _requeue_after_delay |
| `test_poll_upload_fills_limit_delete_still_runs` | upload 큐가 max_per_poll 도달해도 delete 큐는 독립 처리 |
| `test_poll_returns_true_when_upload_hits_limit` | upload 큐가 max_per_poll 도달 시 True 반환 (더 남은 항목 있음 신호) |
| `test_poll_returns_false_when_queues_drained` | 양쪽 큐 소진 시 False 반환 |

### pending 상태 전이

| Test | 검증 내용 |
|------|-----------|
| `test_requeue_after_delay_sets_pending_when_doc_not_running` | 딜레이 후 doc이 끝났으면(not running/deleting) set_pending 후 lpush |
| `test_requeue_after_delay_skips_pending_when_still_running` | 딜레이 후 아직 running이면 set_pending 생략, lpush만 |

---

## 7. Unit — recover API (`tests/unit/test_recover_api.py`)

US-05 구현 검증. `POST /api/kb/{id}/docs/{source}/recover`.

| Test | 검증 내용 |
|------|-----------|
| `test_running_doc_returns_202_and_requeues` | running 문서 → set_failed 호출, pending 설정, upload 큐 재등록, 202 반환 |
| `test_indexed_doc_returns_409` | indexed 문서 → 409 |
| `test_missing_doc_returns_404` | 없는 문서 → 404 |
| `test_failed_doc_returns_409` | failed 문서 → 409 |

---

## 8. Unit — 검색 (`tests/unit/test_search.py`)

### TestRRFMerge

| Test | 검증 내용 |
|------|-----------|
| `test_single_list` | 단일 KB 결과 RRF 점수 계산 |
| `test_deduplication` | 동일 청크 중복 제거 |
| `test_empty_lists` | 빈 결과 처리 |
| `test_multiple_kbs` | 다중 KB 결과 병합 |

### TestSearchSimilarityKb

| Test | 검증 내용 |
|------|-----------|
| `test_uses_dense_only_mode` | similarity 모드에서 dense 벡터만 사용 |
| `test_min_score_filters_low_results` | min_score 미만 결과 필터링 |
| `test_min_score_zero_returns_all` | min_score=0이면 전체 반환 |
| `test_all_below_threshold_returns_empty` | 전체 결과가 임계값 미만이면 빈 리스트 |

---

## 9. Unit — OTel 트레이싱 (`tests/unit/test_tracing.py`)

US-07 구현 검증.

### traceparent 추출

| Test | 검증 내용 |
|------|-----------|
| `test_extract_traceparent_none_ctx` | ctx=None이면 None 반환 |
| `test_extract_traceparent_no_request_context` | request_context 없으면 None 반환 |
| `test_extract_traceparent_meta_is_none` | meta=None이면 None 반환 |
| `test_extract_traceparent_meta_is_dict` | meta dict에 traceparent 없으면 None |
| `test_extract_traceparent_meta_is_dict_missing_key` | meta에 traceparent 키 없으면 None |
| `test_extract_traceparent_meta_pydantic_model_extra` | Pydantic extra 필드에서 traceparent 추출 |
| `test_extract_traceparent_meta_pydantic_model_with_extra` | Pydantic model_extra에서 traceparent 추출 |

### tool_span

| Test | 검증 내용 |
|------|-----------|
| `test_tool_span_creates_span_with_name` | tool_span이 span 이름으로 생성 |
| `test_tool_span_sets_tool_name_attribute` | span에 tool.name 속성 설정 |
| `test_tool_span_with_traceparent_creates_child_span` | traceparent 있으면 child span 생성 |
| `test_tool_span_without_traceparent_creates_root_span` | traceparent 없으면 root span 생성 |
| `test_tool_span_with_traceparent_has_parent` | traceparent 있으면 parent context 연결 |
| `test_tool_span_extra_attributes` | 추가 속성 설정 |
| `test_tool_span_safe_with_noop_provider` | noop provider에서도 안전하게 동작 |

---

## 10. Unit — 검증 Op (`tests/unit/test_validate.py`)

`pipeline/ops/validate.py` — ETag 중복 체크 및 파일 크기 제한.

| Test | 검증 내용 |
|------|-----------|
| `test_validate_new_document` | 신규 문서(Postgres에 없음)는 통과 |
| `test_validate_same_etag_skips` | 동일 ETag → IngestValidationError(skip) |
| `test_validate_different_etag_proceeds` | 다른 ETag → 통과 |
| `test_validate_file_size_exceeded` | 파일 크기 초과 → IngestValidationError |
| `test_validate_processing_same_etag_skips` | running 상태 + 동일 ETag → skip |
| `test_validate_processing_no_etag_proceeds` | running 상태 + ETag 없음 → 통과 |
| `test_validate_force_skips_etag_check` | force=True → ETag 체크 생략 |

---

## 11. Dagster — Event Queue Sensor (`tests/dagster/test_sensor.py`)

`dagster_pipeline/sensors/event_queue_sensor.py` — Dagster sensor 경로 검증.

### 기본 디스패치

| Test | 검증 내용 |
|------|-----------|
| `test_upload_sensor_put_generates_ingest_run` | PUT 이벤트 → ingest_job RunRequest 생성 |
| `test_upload_sensor_delete_generates_delete_run` | DELETE 이벤트 → delete_job RunRequest 생성 |
| `test_upload_sensor_no_events` | 큐 비어있음 → RunRequest 없음 |
| `test_upload_sensor_batch_put` | 다중 PUT 이벤트 → 모두 소비 |
| `test_upload_sensor_mixed_queues` | PUT + DELETE 혼합 → 모두 디스패치 |
| `test_upload_sensor_force_flag_propagated` | force=True → run_config에 전달 |
| `test_sensor_run_keys_unique` | 동일 tick 내 두 이벤트 → run_key 각각 다름 |

### Upload 동시성 처리 (running/deleting 차단)

| Test | 검증 내용 |
|------|-----------|
| `test_sensor_upload_skips_processing_doc` | running + Dagster run 활성 → delay zset 이동, RunRequest 없음 |
| `test_sensor_upload_zombie_run_dispatches` | running + Dagster run 종료 → zombie 복구 후 디스패치 |
| `test_sensor_upload_run_not_found_dispatches` | running + Dagster run_id 미존재 → zombie 복구 후 디스패치 |
| `test_sensor_upload_dispatch_lock_remnant_dispatches` | running + run_id="" (dispatch lock remnant) → 즉시 디스패치 |
| `test_sensor_upload_deleting_with_active_run_delayed` | deleting + active run → delay |
| `test_sensor_upload_deleting_no_run_id_dispatches` | deleting + run_id="" → 즉시 디스패치 |
| `test_sensor_upload_deleting_zombie_run_dispatches` | deleting + dead run → zombie 복구 후 디스패치 |

### Delete 동시성 처리

| Test | 검증 내용 |
|------|-----------|
| `test_sensor_delete_blocked_by_active_run_delayed` | running/deleting + active run → delay |
| `test_sensor_delete_zombie_run_dispatches` | running + dead run → zombie 복구 후 delete 디스패치 |
| `test_sensor_delete_no_run_id_dispatches` | running/deleting + run_id="" → 즉시 디스패치 |

### Delay 큐 및 pending 상태 전이

| Test | 검증 내용 |
|------|-----------|
| `test_sensor_drain_delay_queue` | delay zset 만료 항목 → main 큐 복귀 후 디스패치 |
| `test_drain_delay_queue_sets_pending_when_not_running` | drain 시 doc이 끝났으면 set_pending 호출 |
| `test_drain_delay_queue_skips_pending_when_still_running` | drain 시 doc이 아직 running이면 set_pending 생략 |

---

## 12. Integration — 동시성 가드 (`tests/integration/test_concurrency_guard.py`)

US-02 구현 검증. Sensor / QueueWorker 양쪽 경로.

### TestSensorConcurrencyGuard

| Test | 검증 내용 |
|------|-----------|
| `test_ac1_delete_delayed_while_ingest_processing` | ingest running 중 delete 이벤트 → 차단 |
| `test_ac2_ingest_delayed_while_delete_running` | delete running 중 ingest 이벤트 → 차단 |
| `test_ac1_delete_proceeds_after_ingest_completes` | ingest 완료 후 delete 정상 처리 |
| `test_ac2_ingest_proceeds_after_delete_completes` | delete 완료 후 ingest 정상 처리 |

### TestQueueWorkerConcurrencyGuard

| Test | 검증 내용 |
|------|-----------|
| `test_ac1_delete_delayed_while_ingest_processing` | ingest running 중 delete → 차단 |
| `test_ac2_ingest_delayed_while_delete_running` | delete running 중 ingest → 차단 |
| `test_ac1_delete_proceeds_after_ingest_completes` | ingest 완료 후 delete 정상 처리 |
| `test_ac2_ingest_proceeds_after_delete_completes` | delete 완료 후 ingest 정상 처리 |

---

## 13. Integration — 인제스트 파이프라인 (`tests/integration/test_ingest_pipeline.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_ingest_job_success` | 파이프라인 전 과정(validate → parse → chunk → embed → upsert → meta) 성공 |
| `test_ingest_job_skips_on_same_etag` | 동일 ETag 재요청 시 파이프라인 skip |

---

## 14. Integration — 검색 API (`tests/integration/test_search_api.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_search_returns_results` | 검색 결과 정상 반환 |
| `test_search_empty_kb_ids` | kb_ids 빈 배열 → 빈 결과 |
| `test_search_similarity_mode_with_min_score` | similarity 모드 + min_score 필터 |
| `test_search_invalid_mode_returns_422` | 잘못된 mode → 422 |
| `test_health_liveness` | GET /health → 200 |
