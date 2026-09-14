---
description: design.md+task.md를 코드로 구현 — implementer 서브에이전트 호출, task 단위로 자동 진행
argument-hint: [US-NN 또는 spec 폴더 경로]
---

사용자가 `/spec-implement $ARGUMENTS`로 구현 단계 진행을 요청했다. 폴더 확인과 상태
갱신은 이 커맨드(기계적 작업)가 처리하고, 코드 작성은 `implementer` 서브에이전트에게
맡긴다.

1. `spec-resolve` 스킬을 호출해 spec 폴더를 확정하고 브랜치를 확인한다. 스킬이 멈추면
   (폴더 미확정, 브랜치 불일치) 그 안내를 그대로 전달하고 여기서 중단한다.
2. 그 폴더에 `design.md`나 `task.md`가 없으면 여기서 멈추고 먼저 `/spec-design`부터
   하라고 안내한다.
3. **완료 여부 게이트** — index.md 해당 행 Status가 `implemented`면 여기서 멈춘다
   (implementer 호출 안 함). 이미 구현 완료 상태임을 알리고 `/spec-validate` 또는(설계를
   더 고칠 거면) `/spec-design`을 안내한다.
4. **외부 이상 징후 확인** — `implementation.md` "외부 이상 징후"에 미해결 항목이
   있으면, spec 범위 밖 이슈임을 사용자에게 알리고 이번 실행에서 같이 고칠지 물어본다.
   - **예** — 5번에서 implementer를 호출할 때 그 항목(파일:줄/노드 ID, 에러 내용)을
     같이 전달해 고치라고 지시한다.
   - **아니오** — 항목은 그대로 두고 평소대로 5번으로 진행한다(Task만 처리).
5. `Agent` 툴로 `implementer` 서브에이전트를 호출한다. 전달할 것:
   - spec 폴더 경로
   - `design.md`, `task.md`, `spec.md`의 경로
   - (4번에서 "예"였다면) 고쳐야 할 외부 이상 징후 항목
6. implementer의 반환 결과로 분기한다:
   - **이슈로 정지** — `implementation.md`에 남긴 `blocked` 항목(유형 `[설계]`/`[구현]`
     + 이유)을 그대로 사용자에게 전달한다. `.claude/specs/index.md`의 해당 행 Status를
     `blocked`로 갱신한다(이 세션이 직접 — implementer는 이 파일을 갱신하지 않는다).
     유형이 `[설계]`면 `/spec-design` 재실행을, `[구현]`이면 design.md/task.md는 그대로
     두고 문제를 해소한 뒤 `/spec-implement` 재실행을 안내한다 — 어느 쪽이든 사용자
     지시를 받은 뒤에야 이 커맨드를 다시 실행해 implementer를 재호출한다 — 자동으로
     재시도하지 않는다.
   - **전체 task 완료** — 7번으로 진행.
7. `.claude/specs/index.md`의 해당 행 Status를 `implemented`로 갱신한다(이전 값이
   `designed`든 `blocked`든 상관없이 덮어쓴다).
8. implementer가 작성한 `implementation.md`와 완료된 task 목록을 사용자에게 보여준다.
9. `/spec-validate`로 이어서 진행할지는 사용자 지시에 따른다 — 이 커맨드가 자동으로
   호출하지 않는다. spec.md의 완료 기준(AC) 체크박스와 index.md의 `done` 전환은 이
   커맨드도 implementer도 하지 않는다 — validator 전용이다.
