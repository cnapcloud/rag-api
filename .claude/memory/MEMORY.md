# Memory Index

Claude Code가 세션 간에 학습한 내용을 저장하는 공간.

- [Project Architecture](project_architecture.md) — 전체 아키텍처, 기술 스택, 핵심 파일 위치, 파이프라인 흐름
- [Known Bugs](known_bugs.md) — infra/qdrant.py 미구현, redis.py 부분 구현, embed.py deprecation 경고
- [Feedback & Conventions](feedback_conventions.md) — import 경로 규칙, 테스트 텍스트 패턴, 인프라 Mock 규칙
- [Multi-repo git workflow](feedback_multirepo_git_workflow.md) — patch→main 머지 후 즉시 patch로 복귀, 여러 저장소 작업 시 `git -C` 명시 (persisted cwd 사고 방지)
- [dedup chunk_compare title_match fix](dedup_chunk_compare_title_match_fix.md) — stage escalation 시 title_match 재계산 누락으로 재업로드 문서가 항상 outdated되던 버그 (2026-07-09 수정)
- [dedup chunk_compare containment fix](dedup_chunk_compare_containment_fix.md) — 집계 점수가 containment라 크기 차이 큰 문서쌍도 identical로 오판되던 문제, 청크 수 비율 스케일링으로 수정 (2026-07-09)
- [dedup settings nested by stage](dedup_settings_nested_by_stage.md) — DedupSettings flat 필드를 simhash/minhash/chunk_compare 하위 모델로 재구성, 옛 `dedup.<field>` 경로는 무효 (2026-07-09)
- [html extraction corpus boilerplate rejected](html_extraction_corpus_boilerplate_rejected.md) — corpus 빈도 기반 사이트 boilerplate 자동 탐지는 스트리밍 ingestion과 cold-start 비호환이라 폐기 (2026-07-09)
- [pg_restore schema remap pitfall](pg_restore_schema_remap_pitfall.md) — search_path 무시됨, 전체 치환 시 확장 연산자 클래스 오염, --no-comments 누락 시 owner 에러 (2026-07-11)
- [aiops repo reference](reference_aiops_repo.md) — aiops 저장소 경로, CNPG/MinIO/Qdrant/rag-api 배포 위치, rag-api 서비스가 실제론 rag-ent-api(OIDC) 이미지라는 점 (2026-07-11)
- [Spec-driven traceability system](project_spec_driven_traceability.md) — prd.md/design/backlog/plan 4단 링크 규칙, 하위요건 테이블 US 크로스워크, backlog 템플릿; dedup 영역만 파일럿 적용됨 (2026-07-12)
