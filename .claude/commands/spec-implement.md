---
description: plan.md(+task.md)를 코드로 구현 — implementer 서브에이전트 호출, task 단위로 자동 진행
argument-hint: [US-NN 또는 spec 폴더 경로]
---

사용자가 `/spec-implement $ARGUMENTS`로 구현 단계 진행을 요청했다. 폴더 확인과 상태
갱신은 이 커맨드(기계적 작업)가 처리하고, 코드 작성은 `implementer` 서브에이전트에게
맡긴다.

1. `$ARGUMENTS`가 있으면 이를 기준으로 spec 폴더를 특정한다 (`US-NN` 형태면
   `.claude/specs/US-NN-*/`를 찾는다; 이미 폴더 경로면 그대로 사용). `$ARGUMENTS`가
   없으면 `.claude/specs/index.md`의 "진행 중" 표를 본다 — 행이 정확히 하나면 그 US로
   정한다. 여러 개 매치되거나(인자로 찾은 경우) 진행 중 표에 행이 여러 개거나 하나도
   없으면 사용자에게 어느 spec인지 확인한다.
2. **브랜치 확인** — 그 spec의 spec.md 상단 **상태**가 `done`이 아니면, 현재 git
   브랜치 이름에 `US-NN-`이 포함되는지 확인한다(`/spec-new`가 `<type>/US-NN-<slug>`로
   만든 전용 브랜치). 포함돼 있지 않으면 여기서 멈추고 해당 브랜치로 전환하라고
   안내한다 — 다른 spec의 브랜치나 `main`에서 이어서 진행하면 이 spec과 무관한
   브랜치에 코드가 쓰인다.
3. 그 폴더에 `plan.md`가 없으면 여기서 멈추고 먼저 `/spec-design`부터 하라고 안내한다.
4. `Agent` 툴로 `implementer` 서브에이전트를 호출한다. 전달할 것:
   - spec 폴더 경로
   - `plan.md`, (있으면) `task.md`, `spec.md`의 경로
5. implementer의 반환 결과로 분기한다:
   - **이슈로 정지** (plan.md 설계 결함, 반복해도 안 풀리는 테스트 실패 등) — 지금까지
     완료된 task와 막힌 지점/이유를 그대로 사용자에게 전달한다. spec.md 상단
     **상태**와 `.claude/specs/index.md`의 해당 행 Status를 `blocked`로 갱신한다(이
     세션이 직접 — implementer는 이 두 파일을 갱신하지 않는다). 사용자 지시(plan.md
     수정, `/spec-design` 재실행, 직접 코드 수정 등)를 받은 뒤에야 이 커맨드를 다시
     실행해 implementer를 재호출한다 — 자동으로 재시도하지 않는다.
   - **전체 task 완료** — 6번으로 진행.
6. spec.md 상단 **상태**가 `blocked`였다면 `in-progress`로 되돌리고,
   `.claude/specs/index.md`의 해당 행 Status도 동일하게 동기화한다.
7. implementer가 작성한 `implementation.log`와 완료된 task 목록을 사용자에게 보여준다.
8. `/spec-validate`로 이어서 진행할지는 사용자 지시에 따른다 — 이 커맨드가 자동으로
   호출하지 않는다. spec.md의 완료 기준(AC) 체크박스와 **상태**의 `done` 전환은 이
   커맨드도 implementer도 하지 않는다 — validator 전용이다.
