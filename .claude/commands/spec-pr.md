---
description: validated 상태인 spec을 main으로 PR 요청 — 전체 테스트 스위트 통과 확인 후 PR 생성, 실제 GitHub merge 확인 후 index.md를 History로 이동. 커밋/push는 이 커맨드가 하지만 로컬 merge 커밋은 만들지 않는다
argument-hint: [US-NN 또는 spec 폴더 경로]
---

`/spec-pr $ARGUMENTS`. 서브에이전트 호출 없이 git/GitHub 작업만 기계적으로 처리한다.
로컬에서 main으로 직접 merge하지 않는다 — merge는 GitHub PR을 통해서만 이뤄진다.
`git commit`은 어떤 단계에서도 실행하지 않는다(CLAUDE.md 하드 룰). `git push`/
`gh pr create`는 이 커맨드 호출 자체가 명시적 지시이므로 실행한다.

1. `spec-resolve` 스킬로 spec 폴더 확정 + 브랜치 확인. 스킬이 멈추면 그대로 전달하고
   중단.
2. `.claude/specs/index.md` "진행 중" 표에서 해당 행 Status로 분기:
   - `validated` → PR 생성 경로(3번).
   - `pr_requested` → merge 확인 경로(A1번).
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
   - 실패 → `git merge --abort`. `implementation.md` "진행 기록"에 `blocked` 블록
     append(AC, 유형, 실패 요약). 유형: main 통합/설계 전제 문제면 `[설계]`, 단순
     구현 버그면 `[구현]`. `[구현]`이면 task.md 완료 기준 커버리지 표로 실패 AC의
     Task를 찾아 implementation.md Task 현황에서 `done`→`blocked`로 되돌림.
     index.md Status를 `blocked`로 갱신. 유형에 맞게 `/spec-design`/`/spec-implement`
     재실행 안내.
   - 통과 → 7번.
7. `git merge --abort` → `git checkout <spec 브랜치>`로 원복(main에 로컬 변경 없음).
8. `git push -u origin <spec 브랜치>` → `gh pr create --base main --head <spec 브랜치>
   --title "<spec.md 제목>" --body "..."`(본문: spec.md 요약 + attribution footer).
   PR URL 기록.
9. index.md Status를 `validated` → `pr_requested`로 갱신("진행 중" 표에 유지).
10. `templates/pr.md`대로 spec 폴더에 `pr.md` 작성(있으면 덮어씀). 사용자에게: 테스트
    결과 요약, PR URL, "PR이 merge되면 `/spec-pr` 재요청" 안내. 종료.

## Merge 확인 경로 (`pr_requested`)

A1. `git fetch origin` → `git merge-base --is-ancestor <spec 브랜치> origin/main`.
   - 조상 아님(미merge) → `gh pr view <spec 브랜치> --json state,url,statusCheckRollup`로
     PR 상태를 확인한다.
     - CI 체크 중 `FAILURE`/`ERROR`가 있으면 — PR 빌드 실패로 판단해 `blocked` 처리한다.
       실패한 체크 이름/요약을 `implementation.md` "진행 기록"에 `blocked` 블록으로
       append하고(유형은 CI 로그 내용으로 판단: 코드 문제면 `[구현]`, main과의 통합·
       설계 전제 문제면 `[설계]`), index.md Status를 `pr_requested`에서 `blocked`로
       갱신한다. `pr.md`의 "PR 생성/CI 실패" 섹션 형식으로 실패 정보를 기록해 갱신한다. 유형에 맞게 `/spec-design`/`/spec-implement` 재실행을 안내하고 중단.
     - 체크가 아직 진행 중이거나 전부 통과인데 단순히 아직 merge만 안 된 상태면 —
       현재 상태를 그대로 전달하고("아직 merge되지 않았다") 중단. Status 유지.
   - 조상(merge됨) → A2.
A2. `git checkout main && git pull --ff-only`로 merge된 상태까지 로컬 main을 끌어올린다
   (테스트는 재실행하지 않는다 — PR merge 전 GitHub CI가 이미 그린을 확인했다).
A3. `traceability` 스킬 "`done` 전환 시 확인" 체크리스트대로 index.md "진행 중" 표
   행 삭제 → "History" 표 맨 위에 `| US-NN | <제목> | <오늘 날짜> |` 추가(워킹 트리만,
   미커밋).
A4. `pr.md` 갱신(merge 커밋 해시). "History 이동 커밋은 명시적 요청 시에만" 안내.
