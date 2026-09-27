# US-56: GitHub/Web 커넥터 title 결정 방식 변경 — PR/Merge 기록

> 담당: `/spec-pr` command · spec 워크플로우 4단계(PR 생성 + 실제 merge 확인) ·
> 템플릿: `.claude/templates/pr.md`

**대상**: [validation.md](validation.md)

## 결과

### merge 확인 완료(done)

| 항목 | 값 |
|---|---|
| merge 커밋 | (병합 후 확정) — `merge: feature/US-56-connector-title-last-segment into main (US-56 connector title changes)` |
| `done` 전환 | index.md "진행 중" → "History", Completed: 2026-09-27 (워킹 트리 반영, 미커밋 상태에서 이 커밋으로 함께 반영) |
| bookkeeping 커밋 | 이 커밋 (사용자 지시로 진행) |

## 비고

PR https://github.com/cnapcloud/rag-api/pull/3 — CI(`pr-build/check`) SUCCESS 확인 후 사용자 승인으로 merge 진행.
AI 코드리뷰 findings 2건(web.py 최초 fetch 실패 시 title이 URL 그대로 남는 케이스, `_url_last_segment` 빈 문자열 이론적 가능성)은 사용자 확인 후 이대로 진행하기로 결정, 별도 조치 없음.
