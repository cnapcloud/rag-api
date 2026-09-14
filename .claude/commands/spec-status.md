---
description: 지정한 spec(또는 진행 중 전체)이 spec 워크플로우의 어느 단계까지 왔는지 조회 — 읽기 전용, 아무것도 쓰지 않음
argument-hint: [US-NN 또는 spec 폴더 경로 (생략 시 진행 중 전체)]
---

사용자가 `/spec-status $ARGUMENTS`로 진행 단계 조회를 요청했다. 이 커맨드는 파일을
읽기만 한다 — 아무것도 쓰지 않고, 서브에이전트도 호출하지 않는다.

1. **대상 결정**
   - `$ARGUMENTS`가 있으면 `spec-resolve` 스킬의 "1. spec 폴더 확정" 절차만 써서 spec
     폴더를 하나 특정한다 — 브랜치 확인(2번)은 쓰지 않는다. 조회는 현재 브랜치와
     무관하게 항상 가능해야 한다(다른 spec 브랜치나 `main`에서도 임의 spec의 상태를
     볼 수 있어야 함).
   - 없으면 `.claude/specs/index.md`의 "진행 중" 표 전체를 대상으로 한다. 행이 없으면
     "진행 중인 spec 없음"이라고 알리고 종료한다.
2. **대상 spec마다 아래를 읽는다**:
   - `## 승인` 체크박스 (spec.md)
   - `design.md`/`task.md` 유무
   - `implementation.md` 유무 + "Task 현황" 표의 각 task 상태(todo/in-progress/done/blocked)
   - `validation.md` 유무 + "결론"(전체 통과 / 일부 실패) + 실패 시 유형(`[설계]`/`[구현]`)
   - `.claude/specs/index.md` — 이 US가 "History" 표에 있으면 완료(`done`)로, "진행 중"
     표에 있으면 그 Status 값으로 본다 (상태는 index.md가 유일한 저장소다 — spec.md엔
     별도 상태 필드가 없다).
3. **단계 판정** — 아래 순서대로 첫 매치를 그 spec의 단계로 삼는다:
   - 승인 체크박스가 `[ ]` → **승인 대기** — 다음 액션: 사용자 승인 → `/spec-design`
   - design.md/task.md 없음 → **설계 대기** — 다음 액션: `/spec-design`
   - implementation.md 없음 → **구현 대기** — 다음 액션: `/spec-implement`
   - Task 현황에 `blocked` 있음 → **구현 중단(blocked)** — 그 task의 "진행 기록" 이유와
     유형을 함께 표시. 다음 액션: 유형이 `[설계]`면 `/spec-design`, `[구현]`이면
     `/spec-implement`
   - Task 현황에 `blocked` 없이 `todo`/`in-progress` 남음 → **구현 중** — 다음 액션:
     `/spec-implement`
   - 모든 task `done`, validation.md 없음 → **검증 대기** — 다음 액션: `/spec-validate`
   - validation.md 있고 "일부 실패" → **검증 실패** — 실패 AC 목록 + 유형 표시. 다음
     액션: 유형이 `[설계]`면 `/spec-design`, `[구현]`이면 `/spec-implement`
   - index.md "History" 표에 있음 → **완료**
   - validation.md "전체 통과"이고 index.md Status가 `validated` → **검증 통과 — merge
     대기** — 다음 액션: `/spec-pr`
   - validation.md "전체 통과"인데 index.md Status가 `validated`가 아니고 아직 "진행 중"
     표에 남아있음 → **검증 통과 — validated 전환 누락** (정상 흐름이면 `/spec-validate`가
     전체 통과 시 즉시 Status를 `validated`로 갱신하므로 드문 이상 케이스 — 그대로
     표시하고 원인을 추측하지 않는다)
4. **출력**
   - 대상이 하나면: 판정된 단계, 다음 액션, 판단 근거(어떤 파일의 어떤 값을 봤는지)를
     보여준다.
   - 대상이 여럿(전체 조회)이면: `| Spec | Title | 단계 | 다음 액션 |` 표로 요약한다.
