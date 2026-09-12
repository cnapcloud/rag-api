---
description: 새 spec 항목 시작 — 커밋 상태 확인 + 전용 브랜치 생성 + 번호 채번 + 폴더 생성 + analyst 서브에이전트 호출
argument-hint: [feature|bugfix|patch:] <기능 설명>
---

사용자가 `/spec-new $ARGUMENTS`로 새 spec 작업을 요청했다. 브랜치 생성·번호 채번·폴더
생성은 판단 없이 기계적으로 처리하고, 내용 작성만 `analyst` 서브에이전트에게 맡긴다.

1. **브랜치 확인** — 현재 브랜치가 `main`이 아니면 여기서 멈추고 거부한다. `patch`를
   포함해 다른 어떤 브랜치에서도 `/spec-new`를 시작할 수 없다 — 먼저 `git checkout main`
   으로 전환하라고 안내한다(전환은 사용자가 직접 하게 두고, 이 커맨드가 대신
   전환해주지 않는다 — 다른 브랜치에 있던 이유가 있을 수 있으므로).
2. **작업 트리 확인** — `git status --porcelain`으로 커밋 안 된 변경이 있는지 확인한다
   (staged/unstaged/untracked 전부 포함). 하나라도 있으면 여기서 멈추고 사용자에게 먼저
   커밋하거나 스태시할 것을 안내한다 — 자동으로 커밋하거나 스태시하지 않는다.
3. **타입 파싱** — `$ARGUMENTS`가 `feature:`/`bugfix:`/`patch:` 중 하나로 시작하면 그
   타입을 쓰고 나머지를 요청 설명으로 삼는다. 명시돼 있지 않으면 타입은 `feature`로
   기본 처리하고 `$ARGUMENTS` 전체를 요청 설명으로 쓴다.
4. **main 최신화** — `git pull --ff-only`로 로컬 `main`을 원격과 맞춘다(원격이 없으면
   생략). fast-forward가 안 되면(로컬 `main`이 origin과 갈라짐) 여기서 멈추고 사용자에게
   알린다 — 임의로 merge/rebase하지 않는다.
5. **번호 채번** — `.claude/specs/index.md` "마지막 채번 번호" 필드 + 1을 후보로 삼는다.
   이 spec은 전용 브랜치에서 작업하고 여러 spec이 동시에 진행될 수 있어(서로 아직
   main에 merge되지 않은 상태) 이 필드만으로는 번호가 겹칠 수 있다 — `git branch -a`에서
   `US-<N>` 패턴을 전부 뽑아 그 최댓값 + 1과 비교해서 더 큰 쪽을 최종 US-NN으로 정한다.
6. **슬러그 추출** — 요청 설명에서 짧은 kebab-case slug를 뽑는다.
7. **브랜치 생성** — `git checkout -b <type>/US-NN-<slug>`로 (지금 서 있는, 방금 최신화한)
   `main` 기준의 전용 브랜치를 만들고 전환한다. 이제부터 이 브랜치가 이번 spec의 작업
   공간이다 — `patch` 브랜치는 더 이상 신규 spec 작업에 쓰지 않는다(임시 작업 공간으로만
   남는다).
8. `.claude/specs/US-NN-<slug>/` 폴더를 생성한다.
9. `index.md`의 "마지막 채번 번호"를 방금 정한 US-NN으로 즉시 갱신한다 (analyst 호출 전에
   먼저 갱신 — 번호가 실제로 쓰였다는 사실을 먼저 기록. 12번에서 analyst가 "중복"으로
   판단해 중단하더라도 이 번호는 재사용하지 않고 버린다 — 번호 낭비보다 재사용 충돌이 더
   위험하다).
10. `.claude/templates/spec.md`를 그 폴더 안에 `spec.md`로 복사한다 (내용은 아직
    템플릿 그대로 — analyst가 채운다).
11. `Agent` 툴로 `analyst` 서브에이전트를 호출한다. 전달할 것:
    - spec 폴더 경로 (`.claude/specs/US-NN-<slug>/`)
    - 타입 프리픽스를 제외한 요청 설명 원문
12. analyst의 반환 결과로 분기한다:
    - **중복 판단** ("기존 US-NN에 통합 제안"으로 종료) — spec.md를 채우지 않은 채
      끝난다. `git checkout main`으로 돌아간 뒤 방금 만든 브랜치를 삭제한다
      (`git branch -D <type>/US-NN-<slug>`) — 의미 있는 커밋이 없었으므로 브랜치를 남겨
      두지 않는다. 승인을 묻지 않는다. 폴더/번호는 재사용하지 않는다. 사용자에게 어느
      기존 US로 통합할지 제안만 전달한다.
    - **spec.md 작성 완료** — 13번으로 진행.
13. `.claude/specs/index.md`의 "진행 중" 표에 `| US-NN | <spec.md 제목> | todo |` 한 줄을
    이 세션이 직접 추가한다 (analyst가 아니라 command가 한다 — 번호 채번과 같은 이유로
    판단이 필요 없는 기계적 갱신).
14. analyst가 채운 spec.md 내용을 사용자에게 보여주고 승인 여부를 묻는다.
15. 사용자가 승인하면, **이 세션이 직접** spec.md의 `## 승인` 체크박스를 `[x]`로 갱신한다.
    analyst/designer는 이 체크박스를 스스로 바꾸지 않는다 — 셀프 승인 금지.
16. 승인 전까지는 `/spec-design`으로 넘어가지 않는다. 사용자가 수정을 요청하면 analyst를
    다시 호출하거나 spec.md를 직접 고쳐 반영한 뒤 다시 승인을 묻는다.
