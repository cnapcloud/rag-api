# Memory Index

Claude Code가 세션 간에 학습한 내용을 저장하는 공간. 코드/design 문서/`.claude/rules/`에서
파생 가능한 내용은 여기 두지 않는다 (원본이 stale해질 수 있는 사본을 만들지 않기 위함).

- [Feedback & Conventions](feedback_conventions.md) — SentenceSplitter 테스트 텍스트 함정 (rules 문서에 없는 내용만)
- [Multi-repo git workflow](feedback_multirepo_git_workflow.md) — patch→main 머지 후 즉시 patch로 복귀, 여러 저장소 작업 시 `git -C` 명시 (persisted cwd 사고 방지)
- [pg_restore schema remap pitfall](pg_restore_schema_remap_pitfall.md) — search_path 무시됨, 전체 치환 시 확장 연산자 클래스 오염, --no-comments 누락 시 owner 에러 (2026-07-11)
- [aiops repo reference](reference_aiops_repo.md) — aiops 저장소 경로, CNPG/MinIO/Qdrant/rag-api 배포 위치, rag-api 서비스가 실제론 rag-ent-api(OIDC) 이미지라는 점 (2026-07-11)
- [Spec-driven traceability system 적용 범위](project_spec_driven_traceability.md) — dedup 영역만 파일럿 적용, 나머지 26개 backlog 미소급 (2026-07-12)
- [Backlog done 전환 자동화](feedback_backlog_auto_done_transition.md) — 완료 기준 충족되면 확인 없이 바로 done 전환 + todo/에서 파일 이동 (2026-07-13)
- [Qdrant ensure_collection bare except 함정](qdrant_ensure_collection_bare_except_pitfall.md) — get_collection 실패를 404 여부 안 가리고 삼키면 409 Conflict 유발 (2026-07-13)
- [dedup title_changed 청크 소유권 함정](dedup_title_changed_chunk_ownership_pitfall.md) — Qdrant payload doc_id 재태깅 누락 시 indexed 문서가 청크 0개로 남음 (2026-07-14)
- [웹 커넥터 URL 인코딩 중복생성 함정](web_connector_url_encoding_dedup_pitfall.md) — path percent-encoding/NFC-NFD 미통일로 같은 페이지가 문서 2건으로 중복 생성 (2026-07-14)
- [큐 이벤트가 soft-delete된 문서를 되살리는 함정](queue_resurrection_on_soft_delete_pitfall.md) — connector/KB 삭제 전 큐 정리 누락으로 삭제된 문서가 부활해 영구 404 재시도 (2026-07-14)
- [파서 레지스트리(US-41) 도입 배경](parser_registry_design_rationale.md) — rag-api 공개 확정으로 비공개 파서(캡셔닝/OCR)를 rag-ent-api에서 주입해야 함; E-21로 완료, 관련 문서는 rag-ent-api에 있음 (2026-07-16)
- [docutils RST 스타일시트 함정](docutils_rst_stylesheet_pitfall.md) — publish_string()은 CSS를 <style>로 임베드, 태그 제거만으론 안 지워짐 → publish_parts()['body'] 사용 (2026-07-16)
