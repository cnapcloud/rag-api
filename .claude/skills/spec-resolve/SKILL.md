---
name: spec-resolve
description: spec-design/spec-implement/spec-validate 공통 — $ARGUMENTS로 spec 폴더를 확정하고, done이면 중단, 아니면 현재 git 브랜치가 그 spec 전용 브랜치인지 확인한다.
---

# Spec 폴더 확정 + 브랜치 확인

`/spec-design`, `/spec-implement`, `/spec-validate` 세 커맨드가 공통으로 거치는 앞단
절차다. 각 커맨드는 이 스킬을 호출해 아래 두 가지를 확정한 뒤 자신의 나머지 단계로
넘어간다 — 커맨드마다 따로 적지 않는다.

## 1. spec 폴더 확정

`$ARGUMENTS`가 있으면 그걸로 spec 폴더를 특정한다(`US-NN`이면 `.claude/specs/US-NN-*/`
검색, 폴더 경로면 그대로 사용). 없으면 `index.md` "진행 중" 표를 본다 — 행이 정확히
하나면 그 US로 정하고, 아니면(0개/여러 개) 사용자에게 확인한다.

## 2. 완료 여부 + 브랜치 확인

`.claude/specs/index.md`에서 US-NN이 "History" 표에 있으면(`done`) 여기서 멈춘다 —
"이미 완료된 spec이다. 추가 작업이 필요하면 `/spec-new`로 새 spec을 만들어라"라고
안내하고, 호출한 커맨드는 이후 단계로 진행하지 않는다. `done`된 spec을 제자리에서 다시
여는 건 이 워크플로우가 의도한 경로가 아니다 — History는 완료된 것만 쌓이는 곳이고,
추가 변경은 새 US 번호로 한다.

"진행 중" 표에 있으면(`done`이 아님) 현재 git 브랜치명에 `US-NN-`이 포함되는지
확인한다(`/spec-new`가 `<type>/US-NN-<slug>`로 만든 전용 브랜치). 없으면 멈추고 해당
브랜치로 전환하라고 안내한다 — 다른 브랜치에서 진행하면 무관한 곳에 작업이 남는다.

(`/spec-status`처럼 조회 전용 커맨드는 이 2번을 쓰지 않고 1번만 쓴다 — done인 spec도
조회는 항상 가능해야 한다.)

## 반환

확정된 spec 폴더 경로. 위 조건(폴더 유일성, done 여부, 브랜치 일치) 중 하나라도 걸려
멈췄다면 호출한 커맨드는 이후 단계로 진행하지 않는다.
