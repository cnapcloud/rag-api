# US-NN: <제목> — Merge 기록

> 담당: `/spec-merge` command · spec 워크플로우 4단계(최종, main merge) · 템플릿:
> `.claude/templates/merge.md`

**대상**: [validation.md](validation.md)

## 결과

<`성공` 또는 `실패` 중 하나만 남기고 그 섹션만 채운다.>

### 성공

| 항목 | 값 |
|---|---|
| merge 커밋 | `<hash>` — `<커밋 메시지 첫 줄>` |
| 테스트 스위트 | `<실행한 커맨드>` — `<n> passed, <m> skipped/failed>` |
| bookkeeping 커밋 | `<hash>` — `<커밋 메시지 첫 줄>` |
| `done` 전환 | index.md "진행 중" → "History", Completed: `<날짜>` |
| origin push | 안 함 (사용자 지시 시에만) |

### 실패

| 항목 | 값 |
|---|---|
| 실패 단계 | <충돌(5번) / 테스트(6번) / merge 커밋(7번) / 재실행 가드(4-1번)> |
| 유형 | `[설계]` / `[구현]` / (해당 없음 — 충돌·hook 등 git 자체 이슈) |
| 이유 | <실패한 테스트/충돌 파일 요약, 왜 그런지> |
| 되돌린 것 | <`git merge --abort`로 취소함 / 이미 커밋돼 되돌리지 않음> |
| index.md Status | <`validated` 그대로 / `blocked`로 변경> |
| 다음 액션 | `/spec-design` / `/spec-implement` / 사용자 판단 필요 |

## 비고

<특이사항 없으면 "(없음)">
