# Test Catalog

전체 테스트 목록 및 검증 내용 정리. 346개 수집 기준.

실행 명령:
```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ -v
PYTHONPATH=src .venv/bin/python -m pytest tests/dagster/ -v
PYTHONPATH=src .venv/bin/python -m pytest tests/integration/ -v
```

---

## Unit Tests

### 1. Chunking (`tests/unit/test_chunk.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_chunk_recursive_splits_long_text` | 긴 텍스트가 여러 청크로 분할되는지 |
| `test_chunk_adds_metadata` | 청크에 메타데이터(kb_id, doc_source 등)가 포함되는지 |
| `test_chunk_document_aware_returns_leaf_nodes` | document_aware 전략이 leaf 노드를 반환하는지 (SKIP: 대용량 모델 필요) |
| `test_chunk_single_short_document` | 짧은 문서는 단일 청크로 처리되는지 |

---

### 2. Confluence 커넥터 (`tests/unit/test_confluence_connector.py`)

#### TestInit

| Test | 검증 내용 |
|------|-----------|
| `test_basic_auth_from_email_colon_token` | `email:token` 형식 Basic 인증 설정 |
| `test_bearer_auth_from_pat` | PAT 기반 Bearer 인증 설정 |
| `test_cloud_api_base` | Cloud URL의 API base 경로 생성 |
| `test_custom_max_attachment_mb` | 첨부파일 크기 제한 커스텀 설정 |
| `test_default_max_attachment_mb_is_10` | 첨부파일 크기 제한 기본값 10MB |
| `test_missing_base_url_raises` | base_url 누락 시 ConfigError |
| `test_missing_space_key_raises` | space_key 누락 시 ConfigError |
| `test_no_auth_when_no_secret` | 인증 정보 없으면 auth 헤더 없음 |
| `test_server_api_base` | Server URL의 API base 경로 생성 |

#### TestHasExcludedLabel

| Test | 검증 내용 |
|------|-----------|
| `test_label_check_is_case_insensitive` | 제외 레이블 비교는 대소문자 무시 |
| `test_no_exclude_labels_configured_returns_false` | 제외 레이블 미설정 시 false 반환 |
| `test_page_with_excluded_label_returns_true` | 제외 레이블 포함 페이지 감지 |
| `test_page_without_excluded_label_returns_false` | 제외 레이블 없는 페이지 통과 |

#### TestMakeDownloadUrl

| Test | 검증 내용 |
|------|-----------|
| `test_absolute_url_returned_as_is` | 절대 URL은 그대로 반환 |
| `test_cloud_relative_url_prepends_wiki` | Cloud 상대 URL에 /wiki 접두사 추가 |
| `test_server_relative_url_prepends_base` | Server 상대 URL에 base_url 접두사 추가 |

#### TestProcessPage

| Test | 검증 내용 |
|------|-----------|
| `test_changed_version_restages_and_reenqueues` | 버전 변경된 페이지 재스테이징 및 재큐잉 |
| `test_deleted_doc_is_refetched` | deleted 상태 문서는 재수집 |
| `test_excluded_label_skips_page_and_attachments` | 제외 레이블 페이지는 첨부파일 포함 전체 스킵 |
| `test_new_page_creates_row_stages_and_enqueues` | 신규 페이지 DB 등록 + S3 스테이징 + 큐 투입 |
| `test_s3_failure_sets_failed_and_still_processes_attachments` | S3 실패 시 failed 처리 후 첨부파일은 계속 처리 |
| `test_unchanged_version_skips_staging_but_processes_attachments` | 버전 미변경 페이지 스테이징 스킵, 첨부파일은 처리 |

#### TestProcessAttachment

| Test | 검증 내용 |
|------|-----------|
| `test_all_supported_extensions_accepted` | 지원 확장자 전체 허용 |
| `test_deleted_doc_is_refetched` | deleted 상태 첨부파일 재수집 |
| `test_download_failure_sets_failed` | 다운로드 실패 시 failed 처리 |
| `test_new_attachment_stages_and_enqueues` | 신규 첨부파일 스테이징 + 큐 투입 |
| `test_s3_failure_sets_failed` | S3 업로드 실패 시 failed 처리 |
| `test_too_large_skips` | 크기 초과 첨부파일 스킵 |
| `test_unchanged_version_skips` | 버전 미변경 첨부파일 스킵 |
| `test_unsupported_extension_skips` | 미지원 확장자 스킵 |
| `test_within_size_limit_proceeds` | 크기 이내 첨부파일 정상 처리 |

#### TestSync

| Test | 검증 내용 |
|------|-----------|
| `test_attachment_list_api_failure_is_isolated` | 첨부파일 API 실패는 해당 페이지만 영향, 나머지 계속 |
| `test_sync_processes_all_pages` | 전체 페이지 순회 처리 |

#### TestDispatchSync

| Test | 검증 내용 |
|------|-----------|
| `test_confluence_connector_dispatched` | source_type=confluence 시 ConfluenceConnector 디스패치 |

---

### 3. 커넥터 API (`tests/unit/test_connectors_api.py`)

#### TestCreateConnector

| Test | 검증 내용 |
|------|-----------|
| `test_duplicate_connector_returns_409` | 동일 커넥터 중복 생성 → 409 |
| `test_kb_not_found_returns_404` | KB 없음 → 404 |
| `test_non_web_connector_without_seed_urls_is_accepted` | 비Web 커넥터는 seed_urls 없어도 수락 |
| `test_returns_201_with_connector` | 정상 생성 → 201 + 커넥터 반환 |
| `test_web_connector_with_empty_seed_urls_returns_422` | Web 커넥터 seed_urls 빈 배열 → 422 |
| `test_web_connector_without_seed_urls_returns_422` | Web 커넥터 seed_urls 누락 → 422 |

#### TestGetConnector

| Test | 검증 내용 |
|------|-----------|
| `test_not_found_returns_404` | 없는 커넥터 조회 → 404 |
| `test_returns_connector` | 정상 조회 → 커넥터 반환 |

#### TestListConnectors

| Test | 검증 내용 |
|------|-----------|
| `test_no_filter_passes_none` | 필터 없으면 None 전달 |
| `test_passes_filter_params` | 필터 파라미터 정상 전달 |
| `test_returns_items_list` | 커넥터 목록 반환 |

#### TestPatchConnector

| Test | 검증 내용 |
|------|-----------|
| `test_not_found_returns_404` | 없는 커넥터 수정 → 404 |
| `test_only_unset_fields_passed_to_update` | 미설정 필드만 업데이트에 전달 |
| `test_updates_allowed_fields` | 허용 필드 업데이트 정상 동작 |

#### TestDeleteConnector

| Test | 검증 내용 |
|------|-----------|
| `test_cascade_s3_error_is_ignored` | 커넥터 삭제 시 S3 오류는 무시 |
| `test_cascade_soft_deletes_docs` | 커넥터 삭제 시 연결 문서 소프트 삭제 |
| `test_not_found_returns_404` | 없는 커넥터 삭제 → 404 |
| `test_returns_202_and_triggers_cascade` | 정상 삭제 → 202 + cascade 트리거 |

#### TestTriggerSync

| Test | 검증 내용 |
|------|-----------|
| `test_background_task_marks_error_on_dispatch_failure` | dispatch 실패 시 커넥터 error 처리 |
| `test_not_found_returns_404` | 없는 커넥터 sync → 404 |
| `test_paused_connector_returns_409` | paused 커넥터 sync → 409 |
| `test_returns_202_and_sets_running` | 정상 트리거 → 202 + sync_status=running |
| `test_running_within_timeout_returns_409` | 타임아웃 이내 실행 중 → 409 |
| `test_stale_lock_allows_retrigger` | 오래된 lock은 재트리거 허용 |

#### TestGetSyncStatus

| Test | 검증 내용 |
|------|-----------|
| `test_not_found_returns_404` | 없는 커넥터 → 404 |
| `test_returns_sync_state_and_doc_counts` | sync 상태 + 문서 수 반환 |

#### TestResetSyncStatus

| Test | 검증 내용 |
|------|-----------|
| `test_not_found_returns_404` | 없는 커넥터 → 404 |
| `test_resets_idle_connector_too` | idle 커넥터도 reset 허용 |
| `test_resets_running_to_idle` | running → idle 강제 초기화 |

#### TestListConnectorDocs

| Test | 검증 내용 |
|------|-----------|
| `test_not_found_returns_404` | 없는 커넥터 → 404 |
| `test_page_size_clamped_to_100` | page_size 최대 100 제한 |
| `test_returns_paginated_docs` | 페이지네이션 문서 목록 반환 |

---

### 4. Dedup — MinHash (`tests/unit/test_dedup_minhash.py`)

#### MinHash 핵심 함수

| Test | 검증 내용 |
|------|-----------|
| `test_minhash_signature_length` | MinHash 서명 길이 128 |
| `test_minhash_deterministic` | 동일 입력 → 동일 서명 |
| `test_minhash_identical_token_sets_equal` | 동일 토큰 집합 → 동일 서명 |
| `test_minhash_empty_tokens_returns_128` | 빈 토큰 → 길이 128 반환 |
| `test_minhash_identical_texts_jaccard_one` | 동일 텍스트 Jaccard = 1.0 |
| `test_minhash_unrelated_texts_low_jaccard` | 무관 텍스트 Jaccard 낮음 |

#### 밴드 및 Jaccard

| Test | 검증 내용 |
|------|-----------|
| `test_split_bands_count` | 밴드 수 = num_bands |
| `test_split_bands_deterministic` | 밴드 분할 결과 결정적 |
| `test_split_bands_identical_sigs_equal` | 동일 서명 밴드 일치 |
| `test_compute_jaccard_identical` | 동일 집합 Jaccard = 1.0 |
| `test_compute_jaccard_disjoint` | 교집합 없음 Jaccard = 0.0 |
| `test_compute_jaccard_empty` | 빈 집합 처리 |
| `test_compute_jaccard_partial` | 부분 교집합 Jaccard 계산 |

#### Kiwi 형태소 분석기

| Test | 검증 내용 |
|------|-----------|
| `test_get_kiwi_returns_instance_when_available` | kiwipiepy 설치 시 인스턴스 반환 |
| `test_get_kiwi_returns_none_when_unavailable` | kiwipiepy 미설치 시 None 반환 |
| `test_get_kiwi_missing_user_words_file_logs_warning` | 사용자 단어 파일 없으면 warning 로그 |
| `test_load_user_words_registers_entries` | 사용자 단어 파일 등록 |
| `test_load_user_words_skips_malformed_lines` | 형식 불량 라인 스킵 |

#### run_minhash_detection

| Test | 검증 내용 |
|------|-----------|
| `test_run_minhash_detection_no_candidates_returns_proceed` | 후보 없음 → proceed 반환 |
| `test_run_minhash_detection_saves_signature` | 서명 저장 |
| `test_run_minhash_detection_similar_by_jaccard` | Jaccard 유사도 기준 similar 판정 |
| `test_run_minhash_detection_similar_by_title_above_floor` | 제목 유사도 + Jaccard floor 이상 → similar |
| `test_run_minhash_detection_proceed_when_jaccard_below_floor` | Jaccard floor 미만 → proceed |
| `test_run_minhash_detection_candidate_without_signature_is_skipped` | 서명 없는 후보 스킵 |
| `test_run_minhash_detection_similar_excludes_self` | 자기 자신 제외 |

---

### 5. Dedup — SimHash (`tests/unit/test_dedup_simhash.py`)

#### SimHash 핵심 함수

| Test | 검증 내용 |
|------|-----------|
| `test_simhash_returns_64bit` | SimHash 결과 64비트 정수 |
| `test_simhash_identical_text` | 동일 텍스트 → 동일 해시 |
| `test_simhash_different_texts_differ` | 다른 텍스트 → 다른 해시 |
| `test_simhash_near_duplicate_low_hamming` | 유사 텍스트 Hamming distance 낮음 |
| `test_simhash_ngram3_korean` | 한국어 3-gram 처리 |

#### Hamming / 제목 해시 / 비트 변환

| Test | 검증 내용 |
|------|-----------|
| `test_hamming_identical` | 동일 값 Hamming = 0 |
| `test_hamming_one_bit` | 1비트 차이 Hamming = 1 |
| `test_hamming_all_bits` | 전체 비트 반전 Hamming = 64 |
| `test_title_hash_deterministic` | 제목 해시 결정적 |
| `test_title_hash_different_titles` | 다른 제목 → 다른 해시 |
| `test_title_hash_strips_whitespace` | 공백 제거 후 해시 |
| `test_u64_i64_roundtrip_positive` | 양수 u64/i64 변환 라운드트립 |
| `test_u64_i64_roundtrip_high_bit` | high bit u64/i64 변환 |
| `test_u64_i64_roundtrip_max` | 최대값 u64/i64 변환 |
| `test_get_bands_count` | 밴드 수 검증 |
| `test_get_bands_indices` | 밴드 인덱스 검증 |

#### run_simhash_detection

| Test | 검증 내용 |
|------|-----------|
| `test_run_simhash_detection_no_candidates` | 후보 없음 → proceed |
| `test_run_simhash_detection_identical` | Hamming 0 → identical 판정 |
| `test_run_simhash_detection_title_changed` | 본문 동일 + 제목 변경 → title_changed 판정 |
| `test_run_simhash_detection_similar_hamming_between_thresholds` | identical~similar 사이 Hamming → similar 판정 |
| `test_run_simhash_detection_beyond_similar_threshold_returns_proceed` | similar 임계값 초과 → proceed |
| `test_run_simhash_detection_excludes_self` | 자기 자신 제외 |
| `test_run_simhash_detection_candidate_missing_fingerprint_skipped` | fingerprint 없는 후보 스킵 |

---

### 6. Dedup — Verdict (`tests/unit/test_dedup_verdict.py`)

참고: 테스트 이름의 `a`/`c`는 각각 incoming/existing 문서를 가리킨다.

#### handle_title_changed

| Test | 검증 내용 |
|------|-----------|
| `test_title_changed_no_duplicate_marks_outdated` | duplicate 없으면 incoming outdated 마킹 |
| `test_title_changed_c_newer_marks_a_outdated` | 기존이 더 최신이면 incoming outdated |
| `test_title_changed_a_newer_updates_c` | incoming이 더 최신이면 기존 outdated + payload 갱신 |
| `test_title_changed_c_created_at_null_treats_a_as_newer` | 기존 created_at 없으면 incoming을 newer로 처리 |

#### handle_similar

| Test | 검증 내용 |
|------|-----------|
| `test_similar_no_duplicate_marks_outdated_no_indexing` | duplicate 없으면 incoming outdated, needs_indexing=False |
| `test_similar_c_newer_marks_a_outdated_no_indexing` | 기존이 더 최신 → incoming outdated, needs_indexing=False |
| `test_similar_a_newer_deletes_c_chunks_and_marks_outdated` | incoming이 더 최신 → 기존 청크+밴드 삭제, outdated, needs_indexing=True |
| `test_similar_c_created_at_null_treats_a_as_newer` | 기존 created_at 없으면 incoming을 newer로 처리 |

#### run_verdict

| Test | 검증 내용 |
|------|-----------|
| `test_run_verdict_proceed_no_handler_called` | body_match=none → 핸들러 미호출 |
| `test_run_verdict_identical_dispatches` | body_match=identical_level → handle_identical |
| `test_run_verdict_title_changed_dispatches` | body_match=identical_level + title_match=changed → handle_title_changed |
| `test_run_verdict_similar_dispatches` | body_match=similar → handle_similar |
| `test_run_verdict_unknown_body_match_logs_warning` | 알 수 없는 body_match → warning 로그 |

---

### 7. 문서 생성일자 (`tests/unit/test_doc_created_at.py`)

#### TestExtractDocCreatedAt

| Test | 검증 내용 |
|------|-----------|
| `test_pdf_creation_date` | PDF CreationDate 메타데이터 추출 |
| `test_pdf_no_creation_date_falls_back_to_s3` | PDF CreationDate 없으면 S3 LastModified 폴백 |
| `test_docx_created_date` | DOCX core_properties.created 추출 |
| `test_unsupported_type_falls_back_to_s3` | 미지원 파일 형식 → S3 LastModified 폴백 |
| `test_s3_fallback_failure_returns_empty` | S3 폴백 실패 → 빈 문자열 반환 |
| `test_naive_datetime_coerced_to_utc` | timezone-naive datetime → UTC 처리 |

#### TestUpsertDocCreatedAt

| Test | 검증 내용 |
|------|-----------|
| `test_upsert_result_carries_doc_created_at` | UpsertResult에 doc_created_at 포함 |
| `test_qdrant_payload_includes_doc_created_at` | Qdrant payload에 doc_created_at 포함 |
| `test_qdrant_payload_uses_doc_id_not_doc_key` | payload에 doc_key 대신 doc_id 사용 |
| `test_empty_embedded_nodes_doc_created_at_is_empty` | 임베딩 노드 없으면 doc_created_at 빈 문자열 |

#### TestMetaDocCreatedAt

| Test | 검증 내용 |
|------|-----------|
| `test_parse_op_saves_doc_created_at` | parse_op이 doc_created_at을 Postgres에 저장 |
| `test_parse_op_skips_save_when_doc_created_at_empty` | doc_created_at 빈 문자열이면 저장 생략 |

#### TestReindexKb

| Test | 검증 내용 |
|------|-----------|
| `test_reindex_enqueues_docs_with_changed_etag` | ETag 변경 문서만 큐 투입 |
| `test_reindex_force_enqueues_all` | force=True 시 전체 문서 큐 투입 |
| `test_reindex_skips_docs_with_matching_etag` | ETag 일치 문서 스킵 |
| `test_reindex_skips_docs_without_storage_key` | storage_key 없는 문서 스킵 |

---

### 8. 문서 목록 API (`tests/unit/test_doc_list_api.py`)

`GET /api/kb/{id}/docs` 페이지네이션 / 검색 / 정렬.

#### TestListDocsDefaultResponse

| Test | 검증 내용 |
|------|-----------|
| `test_returns_paginated_shape` | 응답에 items / total / page / page_size 포함 |
| `test_default_params_passed_to_postgres` | 기본 파라미터(page=1, page_size=20, sort=updated_at desc) 전달 |

#### TestListDocsPagination

| Test | 검증 내용 |
|------|-----------|
| `test_page2_passed_correctly` | page=2 파라미터 정상 전달 |
| `test_out_of_range_page_returns_empty_items` | 범위 초과 페이지 → 빈 items |
| `test_page_size_clamped_to_100` | page_size 최대 100 제한 |
| `test_page_less_than_1_returns_422` | page < 1 → 422 |

#### TestListDocsSearch

| Test | 검증 내용 |
|------|-----------|
| `test_search_param_forwarded` | search 파라미터 Postgres 함수에 전달 |
| `test_search_case_insensitive_in_store` | ILIKE 기반 대소문자 무시 검색 |

#### TestListDocsStatusFilter

| Test | 검증 내용 |
|------|-----------|
| `test_status_param_forwarded` | status 파라미터 전달 |
| `test_status_filter_in_store` | 상태 필터링 결과 정확성 |

#### TestListDocsSort

| Test | 검증 내용 |
|------|-----------|
| `test_sort_by_source_param_forwarded` | sort_by 파라미터 전달 |
| `test_sort_by_source_asc_in_store` | source ASC 정렬 |
| `test_doc_source_is_no_longer_valid_sort_field` | doc_source는 유효한 sort 필드 아님 → 422 |
| `test_invalid_sort_by_returns_422` | 허용되지 않는 sort_by → 422 |
| `test_invalid_sort_order_returns_422` | 허용되지 않는 sort_order → 422 |
| `test_null_chunk_count_sorts_last_desc` | chunk_count NULL은 DESC 정렬 시 마지막 |
| `test_null_chunk_count_sorts_last_asc` | chunk_count NULL은 ASC 정렬 시 마지막 |

#### TestListDocsItemShape

| Test | 검증 내용 |
|------|-----------|
| `test_item_fields_present` | 응답 항목에 필수 필드(doc_source, status, etag 등) 포함 |

---

### 9. 임베딩 (`tests/unit/test_embed.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_embed_returns_embedded_nodes` | embed()가 EmbeddedNode 리스트 반환 |
| `test_embed_adds_metadata` | 임베딩 노드에 dense/sparse 벡터 포함 |

---

### 10. GitHub 커넥터 (`tests/unit/test_github_connector.py`)

#### TestConstructor

| Test | 검증 내용 |
|------|-----------|
| `test_defaults` | 기본값 설정 |
| `test_auth_token_from_config` | 인증 토큰 설정 |
| `test_requires_owner` | owner 누락 시 ConfigError |
| `test_requires_repo` | repo 누락 시 ConfigError |

#### TestIterBlobs

| Test | 검증 내용 |
|------|-----------|
| `test_filters_by_supported_extensions` | 지원 확장자 파일만 반환 |
| `test_filters_by_path_prefix` | path_prefix 기준 필터링 |
| `test_max_files_limits_result` | max_files 제한 적용 |

#### TestProcessFile

| Test | 검증 내용 |
|------|-----------|
| `test_new_file_staged` | 신규 파일 S3 스테이징 + 큐 투입 |
| `test_unchanged_file_skipped` | 미변경 파일 스킵 |
| `test_changed_file_reingest` | 변경된 파일 재인제스트 |
| `test_download_failure_marks_failed` | 다운로드 실패 → failed 처리 |
| `test_too_large_file_skipped` | 크기 초과 파일 스킵 |

#### TestChunkCodeRouting

| Test | 검증 내용 |
|------|-----------|
| `test_py_file_uses_code_strategy_metadata` | Python 파일 → code 청킹 전략 메타데이터 |
| `test_pdf_file_uses_text_strategy` | PDF 파일 → text 청킹 전략 |

#### TestParseCodeExtensions

| Test | 검증 내용 |
|------|-----------|
| `test_code_extensions_subset_of_supported` | 코드 확장자는 지원 확장자의 부분집합 |
| `test_code_language_map_covers_all_code_extensions` | 언어 맵이 모든 코드 확장자 포함 |

---

### 11. MCP 도구 (`tests/unit/test_mcp_tools.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_list_knowledge_bases_returns_all` | list_knowledge_bases가 전체 KB 반환 |
| `test_list_knowledge_bases_empty` | KB 없으면 빈 목록 반환 |
| `test_get_document_status_indexed` | indexed 상태 문서 조회 |
| `test_get_document_status_not_found` | 없는 문서 조회 시 not_found 응답 |
| `test_get_document_status_no_size` | file_size 없는 문서 정상 처리 |
| `test_get_document_status_kb_mismatch_is_not_found` | KB 불일치 → not_found 응답 |
| `test_search_with_explicit_kb_ids` | 명시적 kb_ids로 검색 |
| `test_search_expands_to_all_kbs_when_none_specified` | kb_ids 미지정 시 전체 KB 검색 |
| `test_search_returns_empty_when_no_kbs` | KB 없으면 빈 결과 반환 |

---

### 12. HTML 파싱 (`tests/unit/test_parse_html.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_html_clean_reader_returns_single_document` | HTML → 단일 Document 반환 |
| `test_html_clean_reader_strips_nav_footer_script` | nav / footer / script 태그 제거 |
| `test_html_clean_reader_no_body_tag` | body 태그 없는 HTML 처리 |
| `test_html_clean_reader_metadata_contains_file_path` | 메타데이터에 file_path 포함 |
| `test_html_clean_reader_extra_info_merged` | extra_info 메타데이터 병합 |

---

### 13. Postgres CRUD (`tests/unit/test_postgres_crud.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_create_doc_returns_dict` | create_doc이 dict 반환 |
| `test_create_doc_doc_id_is_string` | doc_id가 문자열 타입 |
| `test_get_doc_by_id_found` | doc_id로 문서 조회 성공 |
| `test_get_doc_by_id_not_found` | 없는 doc_id → None 반환 |
| `test_get_doc_by_source_found` | source로 문서 조회 성공 |
| `test_get_doc_by_source_not_found` | 없는 source → None 반환 |
| `test_list_docs_returns_dicts` | list_docs가 dict 리스트 반환 |
| `test_list_docs_excludes_deleted_by_default` | 기본적으로 deleted 문서 제외 |
| `test_list_docs_include_deleted_flag` | include_deleted=True 시 deleted 포함 |
| `test_list_docs_status_filter` | 상태 필터링 정확성 |
| `test_list_docs_paginated_excludes_deleted_by_default` | 페이지네이션 기본으로 deleted 제외 |
| `test_list_docs_paginated_include_deleted` | 페이지네이션 include_deleted=True |
| `test_update_doc_fields_sets_updated_at` | update_doc_fields가 updated_at 갱신 |
| `test_update_doc_fields_noop_on_empty` | 빈 필드 dict → 변경 없음 |
| `test_update_doc_fields_ignores_unknown_keys` | 알 수 없는 키 무시 |
| `test_soft_delete_sets_status_and_deleted_at` | soft_delete → status=deleted + deleted_at 설정 |

---

### 14. QueueWorker (`tests/unit/test_queue_worker.py`)

`pipeline/queue_worker.py` — Redis 큐 소비 및 동시 처리 방어 로직.

#### Poll 동작

| Test | 검증 내용 |
|------|-----------|
| `test_poll_upload_not_processing_dispatches` | upload: 미처리 중 → _run_ingest 디스패치 |
| `test_poll_upload_while_processing_delays` | upload: running(run_id 있음) → delay 큐 이동 |
| `test_poll_upload_while_deleting_discards` | upload: deleting → 이벤트 폐기 |
| `test_poll_delete_not_processing_dispatches` | delete: 미처리 중 → _run_delete 디스패치 |
| `test_poll_delete_while_processing_delays` | delete: running → delay 큐 이동 |
| `test_poll_delete_while_deleting_discards` | delete: deleting → 이벤트 폐기 |
| `test_poll_upload_fills_limit_delete_still_runs` | upload 큐 max_per_poll 도달해도 delete 큐 독립 처리 |
| `test_poll_returns_true_when_upload_hits_limit` | upload 큐 max_per_poll 도달 시 True 반환 |
| `test_poll_returns_false_when_queues_drained` | 양쪽 큐 소진 시 False 반환 |

#### Delay 큐

| Test | 검증 내용 |
|------|-----------|
| `test_drain_delay_queue_moves_ready_items` | 만료된 delay 항목 → main 큐로 복원 |
| `test_drain_delay_queue_skips_future_items` | 미래 score 항목 복원 안 함 |
| `test_duplicate_delay_overwrites_not_accumulates` | 중복 delay 항목은 score만 갱신 (누적 안 함) |

---

### 15. Recover API (`tests/unit/test_recover_api.py`)

#### TestRecoverDocEndpoint

| Test | 검증 내용 |
|------|-----------|
| `test_running_doc_returns_202_and_requeues` | running 문서 → set_failed 후 pending 설정 + 큐 재등록 + 202 |
| `test_indexed_doc_returns_409` | indexed 문서 → 409 |
| `test_missing_doc_returns_404` | 없는 문서 → 404 |
| `test_failed_doc_returns_409` | failed 문서 → 409 |
| `test_kb_mismatch_returns_404` | KB 불일치 → 404 |

---

### 16. 검색 (`tests/unit/test_search.py`)

#### TestRRFMerge

| Test | 검증 내용 |
|------|-----------|
| `test_single_list` | 단일 KB 결과 RRF 점수 계산 |
| `test_deduplication` | 동일 청크 중복 제거 |
| `test_empty_lists` | 빈 결과 처리 |
| `test_multiple_kbs` | 다중 KB 결과 병합 |

#### TestSearchSimilarity

| Test | 검증 내용 |
|------|-----------|
| `test_uses_dense_only_mode` | similarity 모드에서 dense 벡터만 사용 |
| `test_min_score_filters_low_results` | min_score 미만 결과 필터링 |
| `test_min_score_zero_returns_all` | min_score=0이면 전체 반환 |
| `test_all_below_threshold_returns_empty` | 전체 결과 임계값 미만 → 빈 리스트 |

---

### 17. OTel 트레이싱 (`tests/unit/test_tracing.py`)

#### traceparent 추출

| Test | 검증 내용 |
|------|-----------|
| `test_extract_traceparent_none_ctx` | ctx=None → None 반환 |
| `test_extract_traceparent_no_request_context` | request_context 없음 → None 반환 |
| `test_extract_traceparent_meta_is_none` | meta=None → None 반환 |
| `test_extract_traceparent_meta_is_dict` | meta dict에 traceparent 없음 → None |
| `test_extract_traceparent_meta_is_dict_missing_key` | meta에 traceparent 키 없음 → None |
| `test_extract_traceparent_meta_pydantic_model_extra` | Pydantic extra 필드에서 traceparent 추출 |
| `test_extract_traceparent_meta_pydantic_model_with_extra` | Pydantic model_extra에서 traceparent 추출 |

#### tool_span

| Test | 검증 내용 |
|------|-----------|
| `test_tool_span_creates_span_with_name` | span 이름으로 생성 |
| `test_tool_span_sets_tool_name_attribute` | span에 tool.name 속성 설정 |
| `test_tool_span_with_traceparent_creates_child_span` | traceparent 있으면 child span 생성 |
| `test_tool_span_without_traceparent_creates_root_span` | traceparent 없으면 root span 생성 |
| `test_tool_span_with_traceparent_has_parent` | traceparent 있으면 parent context 연결 |
| `test_tool_span_extra_attributes` | 추가 속성 설정 |
| `test_tool_span_safe_with_noop_provider` | noop provider에서도 안전하게 동작 |

---

### 18. 검증 Op (`tests/unit/test_validate.py`)

`pipeline/step/validate.py` — ETag 중복 체크 및 파일 크기 제한.

| Test | 검증 내용 |
|------|-----------|
| `test_validate_doc_not_found` | Postgres에 문서 없으면 통과 |
| `test_validate_normal_doc` | 일반 문서(ETag 다름) 통과 |
| `test_validate_file_size_exceeded` | 파일 크기 초과 → IngestValidationError |
| `test_validate_force_flag_passes` | force=True → ETag 체크 생략 |
| `test_validate_none_size_passes` | file_size=None → 크기 체크 생략 |
| `test_validate_zero_size_passes` | file_size=0 → 크기 체크 생략 |

---

### 19. Web 커넥터 (`tests/unit/test_web_connector.py`)

#### TestAuthConfig

| Test | 검증 내용 |
|------|-----------|
| `test_auth_basic_sets_auth_tuple` | Basic 인증 tuple 설정 |
| `test_auth_headers_merged_into_headers` | 인증 헤더 병합 |
| `test_auth_headers_takes_priority_over_auth_basic` | 인증 헤더가 Basic auth보다 우선 |
| `test_empty_auth_headers_falls_through_to_auth_basic` | 빈 auth_headers → Basic auth 폴백 |
| `test_no_auth_omits_auth_key` | 인증 없으면 auth 키 생략 |

#### TestExtractTitle

| Test | 검증 내용 |
|------|-----------|
| `test_og_title_wins` | og:title이 최우선 |
| `test_article_h1_wins_over_h1` | article 내 h1 > 일반 h1 |
| `test_h1_wins_over_title` | h1 > title 태그 |
| `test_html_title_used_when_no_h1` | h1 없으면 title 태그 사용 |
| `test_empty_h1_falls_through_to_title` | 빈 h1 → title 태그 폴백 |
| `test_empty_og_content_falls_through` | 빈 og:title → 다음 단계 폴백 |
| `test_fallback_url_used_when_no_metadata` | 메타데이터 없으면 URL 사용 |

#### TestHasSufficientContent

| Test | 검증 내용 |
|------|-----------|
| `test_long_content_returns_true` | 충분한 내용 → True |
| `test_short_content_returns_false` | 짧은 내용 → False |
| `test_min_chars_zero_always_true` | min_chars=0 → 항상 True |
| `test_none_extraction_returns_false` | 추출 실패 → False |
| `test_extraction_error_fails_open` | 추출 오류 → fails open (True) |

#### TestIsPaginationUrl

| Test | 검증 내용 |
|------|-----------|
| `test_query_page_param` | ?page=N 패턴 감지 |
| `test_path_page_number` | /page/N 경로 패턴 감지 |
| `test_non_pagination_urls` | 일반 URL은 false |

#### TestShouldProcess

| Test | 검증 내용 |
|------|-----------|
| `test_no_patterns_restricts_to_seed_prefix` | 패턴 없으면 seed prefix 내로 제한 |
| `test_empty_seed_prefixes_blocks_all` | seed prefix 없으면 전체 차단 |
| `test_exclude_pattern_blocks_matching` | 제외 패턴 매칭 URL 차단 |
| `test_include_pattern_filters_non_matching` | 포함 패턴 미매칭 URL 차단 |
| `test_include_pattern_filters_within_seed_scope` | 포함 패턴은 seed 범위 내에서 필터링 |
| `test_exclude_takes_precedence_over_include` | 제외 패턴이 포함 패턴보다 우선 |
| `test_exclude_takes_precedence_over_domain_restriction` | 제외 패턴이 도메인 제한보다 우선 |
| `test_pagination_path_allowed_for_link_discovery` | 페이지네이션 경로는 링크 탐색 허용 |
| `test_pagination_query_allowed_for_link_discovery` | 페이지네이션 쿼리는 링크 탐색 허용 |

#### TestContentFilter

| Test | 검증 내용 |
|------|-----------|
| `test_depth_zero_skips_staging_returns_html` | depth=0 → 스테이징 스킵, HTML 반환 |
| `test_depth_zero_skip_disabled_proceeds_to_stage` | skip_depth_zero=False → 정상 처리 |
| `test_insufficient_content_skips_staging_returns_html` | 내용 부족 → 스테이징 스킵 |
| `test_min_content_chars_zero_disables_check` | min_content_chars=0 → 내용 체크 비활성화 |

#### TestProcessPage

| Test | 검증 내용 |
|------|-----------|
| `test_new_doc_creates_row_stages_and_enqueues` | 신규 URL → DB 등록 + S3 스테이징 + 큐 투입 |
| `test_unchanged_etag_title_same_skips_all` | ETag+제목 미변경 → 전체 스킵 |
| `test_unchanged_etag_updates_title_if_changed` | ETag 미변경 + 제목 변경 → 제목만 업데이트 |
| `test_changed_etag_restages_and_reenqueues` | ETag 변경 → 재스테이징 + 재큐잉 |
| `test_deleted_doc_is_refetched` | deleted 문서 재수집 |
| `test_http_failure_creates_failed_doc_for_new_url` | HTTP 실패 + 신규 URL → failed 문서 생성 |
| `test_http_failure_sets_failed_on_existing_doc` | HTTP 실패 + 기존 문서 → failed 처리 |
| `test_non_html_content_type_skips_processing` | 비HTML 콘텐츠 타입 스킵 |
| `test_s3_failure_sets_failed_and_returns_html_for_link_discovery` | S3 실패 → failed 처리 + 링크 탐색용 HTML 반환 |

#### TestSync

| Test | 검증 내용 |
|------|-----------|
| `test_default_max_pages_is_50` | 기본 max_pages = 50 |
| `test_default_depth_is_2` | 기본 crawl depth = 2 |
| `test_depth_zero_does_not_follow_links` | depth=0 → 링크 미탐색 |
| `test_bfs_discovers_links_at_depth_1` | BFS depth=1 링크 탐색 |
| `test_bfs_does_not_revisit_urls` | BFS 방문한 URL 재방문 안 함 |
| `test_max_pages_limits_crawl` | max_pages 제한 적용 |
| `test_external_domain_blocked_without_include_patterns` | 포함 패턴 없으면 외부 도메인 차단 |
| `test_empty_seed_urls_raises_config_error` | seed_urls 빈 배열 → ConfigError |
| `test_missing_seed_urls_raises_config_error` | seed_urls 누락 → ConfigError |
| `test_queue_size_cap_prevents_memory_bloat` | 큐 크기 상한으로 메모리 과적 방지 |

#### TestDispatchSync

참고: GitHub 커넥터 dispatch 테스트도 이 파일에 있다.

| Test | 검증 내용 |
|------|-----------|
| `test_web_connector_dispatched_for_web_source_type` | source_type=web 시 WebConnector 디스패치 |
| `test_github_connector_dispatched` | source_type=github 시 GitHubConnector 디스패치 |

---

## Dagster Tests

### 20. Event Queue Sensor (`tests/dagster/test_sensor.py`)

`dagster_pipeline/sensors/event_queue_sensor.py` — Dagster sensor 경로 검증.

#### 기본 디스패치

| Test | 검증 내용 |
|------|-----------|
| `test_upload_sensor_put_generates_ingest_run` | PUT 이벤트 → ingest_job RunRequest 생성 |
| `test_upload_sensor_delete_generates_delete_run` | DELETE 이벤트 → delete_job RunRequest 생성 |
| `test_upload_sensor_no_events` | 큐 비어있음 → RunRequest 없음 |
| `test_upload_sensor_batch_put` | 다중 PUT 이벤트 → 모두 소비 |
| `test_upload_sensor_mixed_queues` | PUT + DELETE 혼합 → 모두 디스패치 |
| `test_upload_sensor_force_flag_propagated` | force=True → run_config에 전달 |
| `test_sensor_run_keys_unique` | 동일 tick 내 두 이벤트 → run_key 각각 다름 |

#### Upload 동시성 처리

| Test | 검증 내용 |
|------|-----------|
| `test_sensor_upload_skips_processing_doc` | running + Dagster run 활성 → delay zset 이동 |
| `test_sensor_upload_zombie_run_dispatches` | running + Dagster run 종료(zombie) → 복구 후 디스패치 |
| `test_sensor_upload_run_not_found_dispatches` | running + run_id 미존재(zombie) → 복구 후 디스패치 |
| `test_sensor_upload_dispatch_lock_remnant_dispatches` | running + run_id=""(dispatch lock 잔류) → 즉시 디스패치 |
| `test_sensor_upload_deleting_discarded` | deleting + upload 이벤트 → 폐기 |

#### Delete 동시성 처리

| Test | 검증 내용 |
|------|-----------|
| `test_sensor_delete_blocked_by_active_run_delayed` | running/deleting + active run → delay |
| `test_sensor_delete_zombie_run_dispatches` | running + dead run → zombie 복구 후 delete 디스패치 |
| `test_sensor_delete_no_run_id_dispatches` | running/deleting + run_id="" → 즉시 디스패치 |
| `test_sensor_delete_deleting_discarded` | deleting + delete 이벤트 → 폐기 |

#### Delay 큐 및 pending 상태 전이

| Test | 검증 내용 |
|------|-----------|
| `test_sensor_drain_delay_queue` | delay zset 만료 항목 → main 큐 복귀 후 디스패치 |
| `test_drain_delay_queue_sets_pending_when_not_running` | drain 시 doc이 끝났으면 set_pending 호출 |
| `test_drain_delay_queue_skips_pending_when_still_running` | drain 시 doc이 아직 running이면 set_pending 생략 |

---

## Integration Tests

### 21. 동시성 가드 (`tests/integration/test_concurrency_guard.py`)

Sensor / QueueWorker 양쪽 경로에서 동시성 제어 검증.

#### TestSensorConcurrencyGuard

| Test | 검증 내용 |
|------|-----------|
| `test_ac1_delete_delayed_while_ingest_processing` | ingest running 중 delete 이벤트 → 차단 |
| `test_ac2_ingest_delayed_while_delete_running` | delete running 중 ingest 이벤트 → 차단 |
| `test_ac1_delete_proceeds_after_ingest_completes` | ingest 완료 후 delete 정상 처리 |
| `test_ac2_ingest_proceeds_after_delete_completes` | delete 완료 후 ingest 정상 처리 |

#### TestQueueWorkerConcurrencyGuard

| Test | 검증 내용 |
|------|-----------|
| `test_ac1_delete_delayed_while_ingest_processing` | ingest running 중 delete → 차단 |
| `test_ac2_ingest_delayed_while_delete_running` | delete running 중 ingest → 차단 |
| `test_ac1_delete_proceeds_after_ingest_completes` | ingest 완료 후 delete 정상 처리 |
| `test_ac2_ingest_proceeds_after_delete_completes` | delete 완료 후 ingest 정상 처리 |

---

### 22. 인제스트 파이프라인 (`tests/integration/test_ingest_pipeline.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_ingest_job_success` | 파이프라인 전 과정(validate → parse → chunk → embed → upsert → meta) 성공 |
| `test_ingest_job_validate_passes` | validate 단계 통과 조건 확인 |

---

### 23. 검색 API (`tests/integration/test_search_api.py`)

| Test | 검증 내용 |
|------|-----------|
| `test_search_returns_results` | 검색 결과 정상 반환 |
| `test_search_empty_kb_ids` | kb_ids 빈 배열 → 빈 결과 |
| `test_search_similarity_mode_with_min_score` | similarity 모드 + min_score 필터 |
| `test_search_invalid_mode_returns_422` | 잘못된 mode → 422 |
| `test_health_liveness` | GET /health → 200 |
