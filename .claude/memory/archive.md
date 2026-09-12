# Memory Archive

`MEMORY.md` 인덱스가 15개를 초과하면 가장 오래된 항목부터 여기로 옮기고 `MEMORY.md`에는
최근 5~10개만 남긴다 (`CLAUDE.md` Memory 섹션 규칙). 원본 상세 파일(`.claude/memory/*.md`)은
옮기지 않고 그대로 둔다 — 이 파일은 인덱스 한 줄만 이동한다.

옮길 때는 `MEMORY.md`의 해당 줄을 그대로 잘라 아래 목록에 붙여넣는다 (날짜순 유지).

## Archived Entries

- [Feedback & Conventions](feedback_conventions.md) — SentenceSplitter 테스트 텍스트 함정 (rules 문서에 없는 내용만)
- [Multi-repo git workflow](feedback_multirepo_git_workflow.md) — patch→main 머지 후 즉시 patch로 복귀, 여러 저장소 작업 시 `git -C` 명시 (persisted cwd 사고 방지)
- [pg_restore schema remap pitfall](pg_restore_schema_remap_pitfall.md) — search_path 무시됨, 전체 치환 시 확장 연산자 클래스 오염, --no-comments 누락 시 owner 에러 (2026-07-11)
- [aiops repo reference](reference_aiops_repo.md) — aiops 저장소 경로, CNPG/MinIO/Qdrant/rag-api 배포 위치, rag-api 서비스가 실제론 rag-ent-api(OIDC) 이미지라는 점 (2026-07-11)
- [Qdrant ensure_collection bare except 함정](qdrant_ensure_collection_bare_except_pitfall.md) — get_collection 실패를 404 여부 안 가리고 삼키면 409 Conflict 유발 (2026-07-13)
- [dedup title_changed 청크 소유권 함정](dedup_title_changed_chunk_ownership_pitfall.md) — Qdrant payload doc_id 재태깅 누락 시 indexed 문서가 청크 0개로 남음 (2026-07-14)
