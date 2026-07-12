# Memory Index

Claude Code가 세션 간에 학습한 내용을 저장하는 공간. 코드/design 문서/`.claude/rules/`에서
파생 가능한 내용은 여기 두지 않는다 (원본이 stale해질 수 있는 사본을 만들지 않기 위함).

- [Feedback & Conventions](feedback_conventions.md) — SentenceSplitter 테스트 텍스트 함정 (rules 문서에 없는 내용만)
- [Multi-repo git workflow](feedback_multirepo_git_workflow.md) — patch→main 머지 후 즉시 patch로 복귀, 여러 저장소 작업 시 `git -C` 명시 (persisted cwd 사고 방지)
- [pg_restore schema remap pitfall](pg_restore_schema_remap_pitfall.md) — search_path 무시됨, 전체 치환 시 확장 연산자 클래스 오염, --no-comments 누락 시 owner 에러 (2026-07-11)
- [aiops repo reference](reference_aiops_repo.md) — aiops 저장소 경로, CNPG/MinIO/Qdrant/rag-api 배포 위치, rag-api 서비스가 실제론 rag-ent-api(OIDC) 이미지라는 점 (2026-07-11)
- [Spec-driven traceability system 적용 범위](project_spec_driven_traceability.md) — dedup 영역만 파일럿 적용, 나머지 26개 backlog 미소급 (2026-07-12)
