# US-NN: <제목> — PR/Merge 기록

> 담당: `/spec-pr` command · spec 워크플로우 4단계(PR 생성 + 실제 merge 확인) ·
> 템플릿: `.claude/templates/pr.md`

**대상**: [validation.md](validation.md)

## 결과

<해당하는 섹션 하나만 남기고 채운다: PR 생성 성공 / PR 생성/CI 실패 / merge 확인 완료(done) /
merge 확인 대기중.>

### PR 생성 성공

| 항목 | 값 |
|---|---|
| PR | `<PR URL>` |
| AI 코드리뷰 | `<findings 수>`건 (`medium`, `--comment`) |
| index.md Status | `validated` → `pr_requested` |
| 다음 액션 | CI 결과는 `/spec-pr` 재실행 때 확인, PR이 GitHub에서 merge되면 다시 재실행 |

### PR 생성/CI 실패

| 항목 | 값 |
|---|---|
| 실패 단계 | PR CI 체크 |
| 유형 | `[설계]` / `[구현]` / (해당 없음 — 매핑 안 되는 회귀) |
| 이유 | <실패한 CI 체크 이름/로그 요약, 왜 그런지> |
| index.md Status | <`validated` 그대로 / `pr_requested` → `blocked`로 변경> |
| 다음 액션 | `/spec-design` / `/spec-implement` / 사용자 판단 필요 |

### merge 확인 대기중

| 항목 | 값 |
|---|---|
| PR | `<PR URL>` |
| 현재 상태 | `<gh pr view 결과 — OPEN 등>` |
| index.md Status | `pr_requested` 그대로 |
| 다음 액션 | PR이 merge된 뒤 `/spec-pr` 재실행 |

### merge 확인 완료(done)

| 항목 | 값 |
|---|---|
| merge 커밋 | `<hash>` — `<PR 제목/커밋 메시지 첫 줄>` |
| `done` 전환 | index.md "진행 중" → "History", Completed: `<날짜>` (워킹 트리 반영, 미커밋) |
| bookkeeping 커밋 | 안 함 (사용자 지시 시에만) |

## 비고

<특이사항 없으면 "(없음)">
