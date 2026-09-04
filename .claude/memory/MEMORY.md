# Memory Index

Claude Code가 세션 간에 학습한 내용을 저장하는 공간. 코드/design 문서/`.claude/rules/`에서
파생 가능한 내용은 여기 두지 않는다 (원본이 stale해질 수 있는 사본을 만들지 않기 위함).

- [pptx page_label 타입 함정](pptx_page_label_type_pitfall.md) — 서드파티 리더(PptxReader)가 page_label에 int를 넣어 str 스키마 계약을 깨고, 다중 KB 검색에서만 드러남 (2026-07-27, US-47)
- [HierarchicalNodeParser 함정](hierarchical_node_parser_pitfalls.md) — id_func는 from_defaults() 우회 후 node_parser_map 수동 구성해야 주입됨, NodeRelationship 타입 헬퍼 (2026-07-29, US-03)
- [pydantic scalar-or-list 필드 함정](pydantic_scalar_or_list_field_pitfall.md) — `int | list[int]`에 바로 Field(ge=,le=) 달면 검증 시점에 TypeError, Annotated로 분기별로 감싸야 함 (2026-07-29)
- [로컬 실제 Postgres가 테스트 mock 누락을 가림](local_postgres_masks_missing_test_mocks.md) — 이 워크스테이션엔 localhost:5432 실제 Postgres가 떠 있어 infra.postgres mock 빠뜨려도 로컬에선 통과함 (2026-07-29)
- [JinaEmbedding single-task 함정](jina_embedding_single_task_pitfall.md) — llama-index-embeddings-jinaai는 query/passage task 자동분기·base_url passthrough 없음, embed.py에서 서브클래스로 강제 (2026-09-02, US-50)
- [config.settings ↔ pipeline import 함정](config_settings_pipeline_circular_import_pitfall.md) — settings.py가 chunk.py를 import하면 순환 + llama_index가 Dagster code-server 부팅에 얹혀 probe 실패; chunk_types.py leaf로 분리, Dockerfile은 .pyc 프리컴파일 (2026-09-04)
