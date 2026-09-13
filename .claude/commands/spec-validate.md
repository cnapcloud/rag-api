---
description: spec.md 완료 기준(AC)을 전수 검증 — validator 서브에이전트 호출, 통과 시 validated 전환(main merge는 /spec-merge)
argument-hint: [US-NN 또는 spec 폴더 경로]
---

사용자가 `/spec-validate $ARGUMENTS`로 검증 단계 진행을 요청했다. 폴더 확인과 상태
전환은 이 커맨드(기계적 작업)가 처리하고, 실제 검증만 `validator` 서브에이전트에게
맡긴다.

1. `spec-resolve` 스킬을 호출해 spec 폴더를 확정하고 브랜치를 확인한다. 스킬이 멈추면
   (폴더 미확정, 브랜치 불일치) 그 안내를 그대로 전달하고 여기서 중단한다.
2. 그 폴더에 `design.md`, `task.md`, `implementation.md` 중 하나라도 없으면 여기서
   멈추고 먼저 `/spec-implement`부터 하라고 안내한다.
2-1. **blocked 게이트** — `implementation.md`의 "Task 현황" 표에 `blocked` 상태인
   행이 하나라도 있으면 여기서 멈춘다. validator를 호출하지 않는다 — 완료되지 않은
   task가 있는 채로 검증을 진행하지 않는다. 해당 `blocked` 항목의 "진행 기록" 이유를
   사용자에게 전달하고 `/spec-implement`로 먼저 해소하라고 안내한다.
3. `Agent` 툴로 `validator` 서브에이전트를 호출한다. 전달할 것:
   - spec 폴더 경로
   - `spec.md`, `design.md`, `task.md`, `implementation.md`의 경로
4. validator의 반환 결과로 분기한다:
   - **전체 통과** — 5번으로 진행.
   - **일부 실패 — `[설계]` 유형 포함** — 실패 AC 목록과 이유를 사용자에게 전달한다.
     `.claude/specs/index.md`의 해당 행 Status를 `blocked`로 갱신한다(이 세션이 직접).
     `/spec-design`을 다시 실행해 design.md/task.md를 고치라고 안내한다.
   - **일부 실패 — `[구현]` 유형만** — 실패 AC 목록과 이유를 사용자에게 전달한다.
     index.md Status는 `implemented`로 유지한다(2-1번 `blocked` 게이트를 이미 통과했으므로
     이 시점에 `blocked`일 수 없다). `/spec-implement`를 다시 실행해 남은 AC를 마저
     구현하라고 안내한다.
   실패한 경우 모두 5번(`validated` 전환)으로 넘어가지 않는다.
5. **전체 통과 시 `validated` 전환** — `traceability` 스킬의 문서 정합성 체크리스트를 따른다:
   - `docs/internal/design/`의 관련 토픽 문서가 있으면 그 표/변경 이력에 이번 spec
     반영 여부 확인(반영 필요하면 이 세션이 직접 갱신) — 이 spec 폴더 안의 `design.md`
     (구현 설계)와는 별개다.
   - spec.md/design.md의 설계 링크가 실제로 존재하는 문서를 가리키는지 확인한다.
   - `.claude/specs/index.md`의 "진행 중" 표에서 해당 행 Status를 `validated`로 갱신한다
     (이 세션이 직접 — validator는 이 파일을 갱신하지 않는다). 아직 History로 옮기지
     않는다 — main merge 성공 후 그 확인까지 끝나야 `done`이며, 그건 `/spec-merge`의
     몫이다.
6. validator가 작성한 `validation.md` 내용을 사용자에게 보여주고, `/spec-merge`로
   main에 merge할 수 있다고 안내한다.
