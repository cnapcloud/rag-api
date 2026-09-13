---
description: 승인된 spec.md 기반으로 design.md+task.md 작성 — designer 서브에이전트 호출
argument-hint: [US-NN 또는 spec 폴더 경로]
---

사용자가 `/spec-design $ARGUMENTS`로 설계 단계 진행을 요청했다. 폴더 확인과 상태 갱신은
이 커맨드(기계적 작업)가 처리하고, 내용 작성만 `designer` 서브에이전트에게 맡긴다.

1. `spec-resolve` 스킬을 호출해 spec 폴더를 확정하고 브랜치를 확인한다. 스킬이 멈추면
   (폴더 미확정, 브랜치 불일치) 그 안내를 그대로 전달하고 여기서 중단한다.
2. 그 폴더의 `spec.md`를 읽는다. `## 승인` 체크박스가 `[x]`가 아니면 여기서 멈추고
   사용자에게 먼저 spec.md 승인부터 받으라고 안내한다 — design.md/task.md를 생성하지
   않는다.
3. `design.md`나 `task.md`가 이미 있으면(재실행 케이스) 내용을 사용자에게 보여주고
   처음부터 다시 만들지, 이어서 손볼지 확인한다. 둘 다 없으면 그대로 4번으로 진행한다 —
   템플릿은 designer가 직접 읽어 새로 작성한다.
4. `Agent` 툴로 `designer` 서브에이전트를 호출한다. 전달할 것:
   - spec 폴더 경로 (`.claude/specs/US-NN-<slug>/`)
   - spec.md 경로 (승인 완료 상태임을 이미 확인했다고 함께 전달)
5. designer의 반환 결과로 분기한다:
   - **모순/블로킹 이슈 발견** (예: spec.md가 현재 코드/아키텍처와 충돌) — design.md/
     task.md를 채우지 않은 채 끝난다. 이슈를 그대로 사용자에게 전달하고 spec.md 수정이
     필요한지 확인한다. 상태 갱신(6번)으로 넘어가지 않는다.
   - **design.md/task.md 작성 완료** — 6번으로 진행.
6. spec.md 상단 **상태**를 `in-progress`로 갱신하고, `.claude/specs/index.md`의
   "진행 중" 표에서 해당 US 행의 Status도 `in-progress`로 동기화한다 — 이 세션이 직접
   한다 (designer는 이 두 파일을 갱신하지 않는다).
7. designer가 작성한 design.md와 task.md를 사용자에게 보여준다. 이 둘에는 spec.md 같은
   별도 승인 체크박스가 없으므로 확인은 필수 게이트가 아니지만, 사용자가 수정을 요청하면
   designer를 다시 호출하거나 직접 고쳐 반영한다.
8. `/spec-implement`로 이어서 진행할지는 사용자 지시에 따른다 — 이 커맨드가 자동으로
   호출하지 않는다.
