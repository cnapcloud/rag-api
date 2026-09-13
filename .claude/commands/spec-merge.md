---
description: validated 상태인 spec을 main에 merge — 전체 테스트 스위트 통과 확인 후 커밋, 성공하면 index.md를 History로 이동(done 전환)
argument-hint: [US-NN 또는 spec 폴더 경로]
---

사용자가 `/spec-merge $ARGUMENTS`로 main merge를 요청했다. `/spec-validate`가 AC 전수
검증을 이미 끝낸 spec만 대상으로 하고, 이 커맨드는 git 작업(merge/테스트/커밋/상태
전환)만 기계적으로 처리한다 — 서브에이전트를 호출하지 않는다.

1. `spec-resolve` 스킬을 호출해 spec 폴더를 확정하고 브랜치를 확인한다. 스킬이 멈추면
   그 안내를 그대로 전달하고 여기서 중단한다.
2. **`validated` 게이트** — `.claude/specs/index.md` "진행 중" 표에서 해당 행 Status를
   확인한다. `validated`가 아니면 여기서 멈춘다:
   - `blocked` → `/spec-design` 또는 `/spec-implement`로 먼저 해소하라고 안내.
   - 그 외(`todo`/`specified`/`designed`/`implemented`) → `/spec-validate`부터 통과시키라고
     안내.
3. **작업 트리 확인** — `git status --porcelain`으로 커밋 안 된 변경이 있으면 멈추고
   먼저 커밋/스태시하라고 안내한다(자동으로 커밋하지 않는다 — 이 spec과 무관한 변경이
   섞여 들어갈 수 있다).
4. **main 최신화** — `git checkout main && git pull --ff-only`. fast-forward가 안 되면
   멈추고 사용자에게 알린다(임의로 merge/rebase하지 않는다).
4-1. **이미 merge됐는지 확인(재실행 가드)** — `git merge-base --is-ancestor <spec 브랜치>
   main`으로 확인한다. 이미 main의 조상이면(즉 이전 실행에서 7번 merge 커밋까지는
   성공했는데 9번 bookkeeping 커밋 전에 중단된 상태) 5~7번(merge 시도/테스트/merge
   커밋)을 전부 건너뛰고 바로 8번(`done` 전환)으로 간다 — 이 경우 6번 테스트는 이미
   그 merge 커밋 시점에 통과된 것으로 간주하지 않는다: 재실행 시에도 8번으로 가기 전에
   6번의 테스트 커맨드를 한 번 더 돌려 현재 main 상태가 그린인지 재확인한다(9번
   bookkeeping 커밋이 빠진 것 외에 다른 변경이 없었는지 보장할 방법이 없으므로).
5. **merge 시도(커밋 보류)** — `git merge --no-ff --no-commit <spec 브랜치>`로 merge를
   준비만 하고 커밋하지 않는다.
   - 충돌 발생 → `git merge --abort`로 되돌리고 충돌 파일 목록을 사용자에게 전달한다.
     사용자가 직접 해소하게 하고 여기서 중단한다(임의로 충돌을 해소하지 않는다).
6. **전체 테스트 스위트 실행** — 프로젝트 전체 테스트 커맨드로 확인한다(`Makefile`의
   test 타겟 참고).
   - 실패 → `git merge --abort`로 merge를 취소한다. 실패한 테스트 출력을 사용자에게
     전달하고, spec 브랜치에서 먼저 고친 뒤(필요하면 `/spec-implement` 재실행) 다시
     `/spec-merge`를 실행하라고 안내한다. index.md Status는 `validated`로 그대로 둔다.
   - 통과 → 7번으로 진행.
7. **merge 커밋 확정** — `git commit`으로 5번에서 준비해둔 merge를 확정한다(메시지는
   기존 이력의 `merge: <spec 슬러그> into main (<한 줄 요약>)` 형식을 따른다). 이 커밋이
   성공해야만 8번으로 진행한다 — 실패하면(예: pre-commit hook) 원인을 사용자에게 전달하고
   중단한다.
8. **`done` 전환** — 7번 커밋이 성공한 뒤에만 수행한다. `traceability` 스킬의 "`done` 전환
   시 확인" 체크리스트를 따라 `.claude/specs/index.md`의 "진행 중" 표에서 해당 행을 지우고
   "History" 표 맨 위에 `| US-NN | <제목> | <오늘 날짜> |`로 옮긴다.
9. **bookkeeping 커밋** — 8번에서 바꾼 `index.md`만 별도로 커밋한다(메시지 예:
   `docs(specs): move US-NN to done`). 이 커밋까지 성공해야 전체 과정이 끝난 것으로 본다.
10. 결과를 사용자에게 보여준다: merge 커밋 해시, 테스트 스위트 결과 요약, `done` 전환
    완료 여부. `origin`에 push할지는 사용자 지시에 따른다 — 이 커맨드가 자동으로
    push하지 않는다.
