# Memory Index

Claude Code가 세션 간에 학습한 내용을 저장하는 공간.

- [Project Architecture](project_architecture.md) — 전체 아키텍처, 기술 스택, 핵심 파일 위치, 파이프라인 흐름
- [Known Bugs](known_bugs.md) — infra/qdrant.py 미구현, redis.py 부분 구현, embed.py deprecation 경고
- [Feedback & Conventions](feedback_conventions.md) — import 경로 규칙, 테스트 텍스트 패턴, 인프라 Mock 규칙
- [dedup chunk_compare title_match fix](dedup_chunk_compare_title_match_fix.md) — stage escalation 시 title_match 재계산 누락으로 재업로드 문서가 항상 outdated되던 버그 (2026-07-09 수정)
- [dedup chunk_compare containment fix](dedup_chunk_compare_containment_fix.md) — 집계 점수가 containment라 크기 차이 큰 문서쌍도 identical로 오판되던 문제, 청크 수 비율 스케일링으로 수정 (2026-07-09)
- [dedup settings nested by stage](dedup_settings_nested_by_stage.md) — DedupSettings flat 필드를 simhash/minhash/chunk_compare 하위 모델로 재구성, 옛 `dedup.<field>` 경로는 무효 (2026-07-09)
