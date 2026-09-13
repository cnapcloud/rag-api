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
3. **design.md/task.md 기존 파일 확인** — design.md와 task.md가 둘 다 없으면 신규
   케이스다. 3-1을 건너뛰고 4번으로 진행한다.

   하나라도 존재하면 `.claude/specs/index.md`에서 해당 spec의 Status를 확인한다.
   - `blocked` → 재작업 케이스이므로 3-1로 진행한다.
   - `specified` 또는 `todo` → 설계가 중단되어 잔여 파일이 남은 케이스다.
   - `designed` → 설계가 이미 완료된 케이스다.
   - `implemented` → 해당 설계를 기반으로 코드가 이미 구현된 케이스다.

   `blocked`가 아닌 기존 파일이 발견되면 designer를 호출하지 않는다. 파일 존재 사실과
   현재 Status를 사용자에게 보여주고 지시를 기다린다.

   - `specified`/`todo`에서 계속 진행 → 지시 원문을 재작업 사유로 삼아 4번부터
     진행한다.
   - `designed`에서 계속 진행 → `/spec-implement`를 안내하고 종료한다.
   - `implemented`에서 계속 진행 → `/spec-validate`를 안내하고 종료한다.
   - 구체적인 수정 요청 → 해당 요청을 재작업 사유로 삼아 설계 작업을 진행한다. 단,
     `implemented`에서는 설계 재작업으로 가지 않고 안내만 한다.
3-1. **재작업 사유 추출 + 유형 게이트** — `validation.md`가 있고 `[설계]` 유형 FAIL
   항목이 있으면 그 AC ID + 이유를 추출하고 4번으로 진행한다(이 경로는 validator가
   이미 `[설계]` 유형임을 확정한 뒤에만 Status를 `blocked`로 세팅하므로 유형 확인이
   필요 없다). 그렇지 않으면(구현/merge 단계에서 막힌 경우) `implementation.md` "진행 기록"의
   가장 최근 `blocked` 블록에서 AC + 유형 + 이유를 추출한다:
   - 유형이 `[구현]`이면 — 설계 문제가 아니므로 여기서 멈춘다. designer를 호출하지
     않는다. 추출한 이유를 사용자에게 전달하고 `/spec-implement`로 먼저 해소하라고
     안내한다.
   - 유형이 `[설계]`면 계속 진행한다.
   어느 파일을 볼지, 유형이 무엇인지는 상태만 보면 기계적으로 판단 가능하므로 이
   세션이 직접 한다. 추출한 AC + 이유는 4번에서 designer에게 함께 전달한다.
4. `Agent` 툴로 `designer` 서브에이전트를 호출한다. 전달할 것:
   - spec 폴더 경로 (`.claude/specs/US-NN-<slug>/`)
   - spec.md 경로 (승인 완료 상태임을 이미 확인했다고 함께 전달)
   - (재작업 케이스면) 3-1번에서 추출한 재작업 사유 원문
5. designer의 반환 결과로 분기한다:
   - **모순/블로킹 이슈 발견** (예: spec.md가 현재 코드/아키텍처와 충돌, 또는 재작업
     케이스에서 재작업 사유가 요구하는 설계 변경이 기존 구조와 근본적으로 맞지 않아
     기존 design.md를 그대로 고쳐서는 해소할 수 없는 경우) — design.md/task.md를 채우지
     않은 채(재작업 케이스면 기존 내용을 그대로 둔 채) 끝난다. 이슈를 그대로 사용자에게
     전달하고 spec.md 수정이 필요한지 확인한다. 상태 갱신(6번)으로 넘어가지 않는다 —
     재작업 케이스라면 Status도 `blocked`로 그대로 남긴다.
   - **design.md/task.md 작성 완료** — 6번으로 진행.
6. `.claude/specs/index.md`의 "진행 중" 표에서 해당 US 행의 Status를 `designed`로
   갱신한다 — 이 세션이 직접 한다 (designer는 이 파일을 갱신하지 않는다). 재작업
   케이스였다면 이 갱신이 `blocked`를 대체한다.
7. designer가 작성한 design.md와 task.md를 사용자에게 보여준다. 이 둘에는 spec.md 같은
   별도 승인 체크박스가 없으므로 확인은 필수 게이트가 아니지만, 사용자가 수정을 요청하면
   designer를 다시 호출하거나 직접 고쳐 반영한다.
8. `/spec-implement`로 이어서 진행할지는 사용자 지시에 따른다 — 이 커맨드가 자동으로
   호출하지 않는다.
