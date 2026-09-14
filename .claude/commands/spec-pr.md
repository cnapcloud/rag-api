---
description: validated 상태인 spec을 main으로 PR 요청 — 전체 테스트 스위트 통과 확인 후 PR 생성, 실제 GitHub merge 확인 후 index.md를 History로 이동. 커밋/push는 이 커맨드가 하지만 로컬 merge 커밋은 만들지 않는다
argument-hint: [US-NN 또는 spec 폴더 경로]
---

`/spec-pr $ARGUMENTS`. 서브에이전트 호출 없이 git/GitHub 작업만 기계적으로 처리한다.
로컬에서 main으로 직접 merge하지 않는다 — merge는 GitHub PR을 통해서만 이뤄진다.
`git commit`은 어떤 단계에서도 실행하지 않는다(CLAUDE.md 하드 룰). `git push`/
`gh pr create`는 이 커맨드 호출 자체가 명시적 지시이므로 실행한다. `gh pr merge`는
CI 통과 후 사용자에게 별도로 물어(6번) "예"를 받은 경우에만 실행한다 — merge는
여전히 GitHub PR 기능을 통해서만 이뤄진다(로컬 merge 커밋 없음).

1. `spec-resolve` 스킬로 spec 폴더 확정 + 브랜치 확인. 스킬이 멈추면 그대로 전달하고
   중단.
2. `.claude/specs/index.md` "진행 중" 표에서 해당 행 Status로 분기:
   - `validated` → PR 생성 경로(3번).
   - `pr_requested` → PR Build 확인(3번).
   - `blocked` → `/spec-design` 또는 `/spec-implement`로 먼저 해소하라고 안내, 중단.
   - 그 외 → `/spec-validate`부터 통과시키라고 안내, 중단.

## PR 생성 경로 (`validated`)

3. `git status --porcelain`으로 워킹 트리 확인. 변경 있으면 먼저 커밋/스태시하라고
   안내하고 중단(자동 커밋 안 함).
4. `git checkout main && git pull --ff-only`. fast-forward 실패 시 중단하고 알림
   (임의로 merge/rebase 안 함).
5. `git merge --no-ff --no-commit <spec 브랜치>`로 드라이런(충돌·회귀를 PR 전에
   미리 확인하는 용도 — 나중에 반드시 abort). 충돌 시 `git merge --abort` 후 충돌
   파일 목록을 전달하고 중단(임의로 해소 안 함).
6. 드라이런 상태에서 전체 테스트 스위트 실행(`Makefile` test 타겟).
   - 실패 → `git merge --abort` → `git checkout <spec 브랜치>`로 원복(main에 로컬 변경
     없이, 실패해도 항상 spec 브랜치로 돌아온다). `regression-triage` 스킬대로 실패를
     분류해 기록·안내하고 중단한다(7번으로 넘어가지 않음).
   - 통과 → 7번.
7. `git merge --abort` → `git checkout <spec 브랜치>`로 원복(main에 로컬 변경 없음).
8. `git push -u origin <spec 브랜치>`. `gh pr view <spec 브랜치> --json url,state`로
   이미 열린 PR이 있는지 확인한다(CI 실패 등으로 `blocked`됐다가 고쳐서 다시
   `validated`로 돌아온 재요청일 수 있음):
   - `OPEN`인 PR이 있으면 `gh pr create`는 건너뛴다 — 같은 브랜치라 push만으로 그
     PR에 커밋이 반영되고 CI가 재실행된다. 기존 PR URL을 그대로 쓴다.
   - 없으면(또는 `CLOSED`/`MERGED`) `gh pr create --base main --head <spec 브랜치>
     --title "<spec.md 제목>" --body "..."`(본문: spec.md 요약 + attribution footer)로
     새로 만든다. PR URL 기록.
9. index.md Status를 `validated` → `pr_requested`로 갱신("진행 중" 표에 유지).
10. `templates/pr.md`대로 spec 폴더에 `pr.md` 작성(있으면 덮어씀). 사용자에게: 테스트
    결과 요약, PR URL, "PR이 merge되면 `/spec-pr` 재요청" 안내. 종료.

## PR Build 확인 (`pr_requested`)

3. `gh pr view <spec 브랜치> --json state,statusCheckRollup`로 PR 상태와 CI 체크를
   확인한다.
4. CI 체크 중 `FAILURE`/`ERROR`가 있으면 중단한다: `regression-triage` 스킬대로 실패를
   분류해 기록·안내하고(CI 로그 기준 매핑 판단), `pr.md`를 "PR 생성/CI 실패" 섹션으로
   갱신한다.
5. (4 아님) 체크가 하나도 없거나 아직 진행 중인 게 남아있으면 "체크가 끝날 때까지
   기다려 달라"고 안내하고 중단. Status 유지.
6. (4/5 아님, 즉 체크가 하나 이상 있고 전부 완료+`SUCCESS`) `state`가 이미 `MERGED`면
   그대로 7번으로. `OPEN`이면 지금 merge할지 물어본다:
   - **아니오** — "CI 통과, merge 대기 중"이라고 보고하고 중단한다. Status 유지,
     `pr.md`도 갱신하지 않는다.
   - **예** — `gh pr merge <spec 브랜치> --merge`(이 repo는 merge commit 방식을 씀,
     제목은 기존 관례 `merge: <spec 브랜치> into main (<요약>)`)로 실제 merge를
     실행한 뒤 7번으로.
7. `git checkout main && git pull --ff-only`로 merge된 상태까지 로컬 main을 끌어올린다
   (테스트는 재실행하지 않는다 — PR merge 전 GitHub CI가 이미 그린을 확인했다).
8. `traceability` 스킬 "`done` 전환 시 확인" 체크리스트대로 index.md "진행 중" 표
   행 삭제 → "History" 표 맨 위에 `| US-NN | <제목> | <오늘 날짜> |` 추가(워킹 트리만,
   미커밋).
9. `pr.md` 갱신(merge 커밋 해시). "History 이동 커밋은 명시적 요청 시에만" 안내.
