---
description: validated 상태인 spec을 main에 merge — 전체 테스트 스위트 통과 확인 후 index.md를 History로 이동, 커밋은 사용자가 직접 요청할 때만
argument-hint: [US-NN 또는 spec 폴더 경로]
---

사용자가 `/spec-merge $ARGUMENTS`로 main merge를 요청했다. `/spec-validate`가 AC 전수
검증을 이미 끝낸 spec만 대상으로 하고, 이 커맨드는 git 작업(merge/테스트/상태 전환)만
기계적으로 처리한다 — 서브에이전트를 호출하지 않는다. **이 커맨드는 어떤 단계에서도
`git commit`을 실행하지 않는다**(CLAUDE.md 하드 룰 — 커밋은 사용자가 명시적으로 요청할
때만, 이 커맨드가 끝난 뒤 별도 요청으로 이뤄진다).

1. `spec-resolve` 스킬을 호출해 spec 폴더를 확정하고 브랜치를 확인한다. 스킬이 멈추면
   그 안내를 그대로 전달하고 여기서 중단한다.
2. **`validated` 게이트** — `.claude/specs/index.md` "진행 중" 표에서 해당 행 Status를
   확인한다. `validated`가 아니면 여기서 멈춘다:
   - `blocked` → `/spec-design` 또는 `/spec-implement`로 먼저 해소하라고 안내.
   - 그 외(`todo`/`specified`/`designed`/`implemented`) → `/spec-validate`부터 통과시키라고
     안내.
3. **작업 트리 확인** — `git status --porcelain`으로 커밋 안 된 변경이 있으면 멈추고
   먼저 커밋/스태시하라고 안내한다(자동으로 커밋하지 않는다 — 이 spec과 무관한 변경이
   섞여 들어갈 수 있다). main merge 직전이 워킹 트리 클린을 요구하는 자연스러운
   지점이다 — design/implement/validate 단계 사이사이는 이 체크를 두지 않는다.
4. **main 최신화** — `git checkout main && git pull --ff-only`. fast-forward가 안 되면
   멈추고 사용자에게 알린다(임의로 merge/rebase하지 않는다).
4-1. **이미 merge됐는지 확인(재실행 가드)** — `git merge-base --is-ancestor <spec 브랜치>
   main`으로 확인한다. 조상이 아니면(정상 케이스) 5번으로 진행한다.

   이미 조상이면 — 이전 실행에서 사용자가 merge를 이미 커밋했다는 뜻이다(이 커맨드는
   커밋을 하지 않으므로 사용자가 직접 했을 때만 가능). `.claude/specs/index.md` 해당
   행 Status가 아직 `validated`인지 확인한다:
   - 이미 History에 있음 → `spec-resolve`의 done 게이트가 1번에서 이미 걸렀을 것이므로
     여기 도달하지 않는다(정상이면 발생 안 함).
   - 아직 `validated`(진행 중 표에 남음) → bookkeeping(index.md → History 반영)이 아직
     안 된 상태다. 6번의 테스트를 다시 돌려 현재 main이 그린인지 확인한 뒤(동일하게
     실패 처리), 통과하면 8번(`done` 전환 — 파일만 수정, 미커밋)으로 바로 간다.
5. **merge 시도(커밋 보류)** — `git merge --no-ff --no-commit <spec 브랜치>`로 merge를
   워킹 트리에 준비만 하고 커밋하지 않는다.
   - 충돌 발생 → `git merge --abort`로 되돌리고 충돌 파일 목록을 사용자에게 전달한다.
     사용자가 직접 해소하게 하고 여기서 중단한다(임의로 충돌을 해소하지 않는다).
6. **전체 테스트 스위트 실행** — 프로젝트 전체 테스트 커맨드로 확인한다(`Makefile`의
   test 타겟 참고).
   - 실패 → `git merge --abort`로 merge를 취소한다(4-1에서 재진입한 경우는 되돌릴 merge
     자체가 없으므로 이 abort는 생략). `implementation.md`의 "진행 기록"에 `blocked`
     블록을 append한다(AC, 유형 `[설계]`/`[구현]`, 실패 테스트 요약과 이유 —
     implementer/validator가 남기는 형식과 동일). 유형 판단은 이 세션이 직접 한다:
     merge 자체가 원인(다른 spec과의 통합 충돌)이거나 design.md의 전제가 main 최신
     상태와 어긋난 경우 `[설계]`, 그 외 단순 구현 누락/버그는 `[구현]`.
     유형이 `[구현]`이면 — implementer의 재개 로직(`implementer.md` 2번, "Task 현황"에서
     `done`이 아닌 첫 항목부터 진행)이 이 회귀를 집어낼 수 있도록, task.md의 "완료 기준
     커버리지" 표에서 실패한 AC를 담당하는 Task ID를 찾아 `implementation.md`의 "Task
     현황" 표에서 그 Task 상태도 `done` → `blocked`로 되돌린다(모든 task가 이미
     `done`인 상태로 남아있으면 implementer가 재실행 시 손댈 게 없다고 보고 곧장
     종료해버린다). `[설계]`면 이 표는 건드리지 않는다(designer는 Task 현황을 보지
     않는다). `.claude/specs/index.md` Status를 `validated`에서 `blocked`로 갱신한다.
     유형이 `[설계]`면 `/spec-design`, `[구현]`이면 `/spec-implement`를 다시 실행해 해소하라고
     안내한다.
   - 통과 → 7번으로 진행(최종 완료 처리).
7. **최종 완료 처리** — 테스트가 통과했으므로 이 spec은 완료로 확정한다. `traceability`
   스킬의 "`done` 전환 시 확인" 체크리스트를 따라 `.claude/specs/index.md`의 "진행 중"
   표에서 해당 행을 지우고 "History" 표 맨 위에 `| US-NN | <제목> | <오늘 날짜> |`로
   옮긴다. 이 변경도 merge와 마찬가지로 워킹 트리에만 반영하고 커밋하지 않는다 — merge로
   준비된 변경 + 이 index.md 변경이 합쳐진 상태 그대로 둔다.
8. **결과 보고 + 커밋 안내** — `templates/merge.md` 템플릿을 그대로 따라 spec 폴더에
   `merge.md`를 쓴다(이미 있으면 덮어쓴다). 사용자에게 보여줄 내용:
   - 테스트 스위트 결과 요약(몇 개 통과/스킵)
   - 워킹 트리에 반영된 변경 요약(merge 대상 브랜치, index.md의 History 이동 포함)
   - "커밋하려면 명시적으로 요청해달라"는 안내(이 커맨드는 커밋하지 않는다 — CLAUDE.md
     하드 룰). `origin` push 여부도 마찬가지로 사용자 지시가 있어야 한다.
   보고를 마치면 커맨드를 종료한다 — 커밋은 이후 별도 사용자 요청으로 처리한다.
