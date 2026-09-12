---
description: backlog.md 완료 기준(AC)을 전수 검증 — validator 서브에이전트 호출, 통과 시 done 전환
argument-hint: [US-NN 또는 spec 폴더 경로]
---

사용자가 `/spec-validate $ARGUMENTS`로 검증 단계 진행을 요청했다. 폴더 확인과 상태
전환은 이 커맨드(기계적 작업)가 처리하고, 실제 검증만 `validator` 서브에이전트에게
맡긴다.

1. `$ARGUMENTS`가 있으면 이를 기준으로 spec 폴더를 특정한다 (`US-NN` 형태면
   `.claude/specs/US-NN-*/`를 찾는다; 이미 폴더 경로면 그대로 사용). `$ARGUMENTS`가
   없으면 `.claude/specs/index.md`의 "진행 중" 표를 본다 — 행이 정확히 하나면 그 US로
   정한다. 여러 개 매치되거나(인자로 찾은 경우) 진행 중 표에 행이 여러 개거나 하나도
   없으면 사용자에게 어느 spec인지 확인한다.
2. **브랜치 확인** — 그 spec의 backlog.md 상단 **상태**가 `done`이 아니면, 현재 git
   브랜치 이름에 `US-NN-`이 포함되는지 확인한다(`/spec-new`가 `<type>/US-NN-<slug>`로
   만든 전용 브랜치). 포함돼 있지 않으면 여기서 멈추고 해당 브랜치로 전환하라고
   안내한다 — 다른 spec의 브랜치나 `main`에서 이어서 진행하면 이 spec과 무관한
   브랜치에서 검증/AC 체크박스 갱신이 이뤄진다.
3. 그 폴더에 `plan.md`나 `implementation.log`가 없으면 여기서 멈추고 먼저
   `/spec-implement`부터 하라고 안내한다.
4. `Agent` 툴로 `validator` 서브에이전트를 호출한다. 전달할 것:
   - spec 폴더 경로
   - `backlog.md`, `plan.md`, (있으면) `task.md`, `implementation.log`의 경로
5. validator의 반환 결과로 분기한다:
   - **전체 통과** — 6번으로 진행.
   - **일부 실패 — `[설계]` 유형 포함** — 실패 AC 목록과 이유를 사용자에게 전달한다.
     backlog.md 상단 **상태**와 `.claude/specs/index.md`의 해당 행 Status를 `blocked`로
     갱신한다(이 세션이 직접). `/spec-design`을 다시 실행해 plan.md를 고치라고 안내한다.
   - **일부 실패 — `[구현]` 유형만** — 실패 AC 목록과 이유를 사용자에게 전달한다. 상태는
     `in-progress`로 유지(또는 `blocked`였다면 되돌림). `/spec-implement`를 다시 실행해
     남은 AC를 마저 구현하라고 안내한다.
   실패한 경우 모두 7번(`done` 전환)으로 넘어가지 않는다.
6. **전체 통과 시 `done` 전환** — `traceability` 스킬의 done 전환 체크리스트를 따른다:
   - design 문서가 있으면 그 표/변경 이력에 이번 spec 반영 여부 확인(반영 필요하면
     이 세션이 직접 갱신).
   - backlog.md 상단 **상태**를 `done`으로 갱신.
   - `.claude/specs/index.md`의 "진행 중" 표에서 해당 행을 지우고 "History" 표 맨 위에
     `| US-NN | <제목> | <오늘 날짜> |`로 옮긴다.
   - backlog.md/plan.md의 설계 링크가 실제로 존재하는 문서를 가리키는지 확인한다.
7. validator가 작성한 `test_result.md` 내용을 사용자에게 보여준다.
