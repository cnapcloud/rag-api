---
name: spec-resolve
description: spec-design/spec-implement/spec-validate 공통 — $ARGUMENTS로 spec 폴더를 확정하고 현재 git 브랜치가 그 spec 전용 브랜치인지 확인한다.
---

# Spec 폴더 확정 + 브랜치 확인

`/spec-design`, `/spec-implement`, `/spec-validate` 세 커맨드가 공통으로 거치는 앞단
절차다. 각 커맨드는 이 스킬을 호출해 아래 두 가지를 확정한 뒤 자신의 나머지 단계로
넘어간다 — 커맨드마다 따로 적지 않는다.

## 1. spec 폴더 확정

`$ARGUMENTS`가 있으면 이를 기준으로 spec 폴더를 특정한다 (`US-NN` 형태면
`.claude/specs/US-NN-*/`를 찾는다; 이미 폴더 경로면 그대로 사용). `$ARGUMENTS`가 없으면
`.claude/specs/index.md`의 "진행 중" 표를 본다 — 행이 정확히 하나면 그 US로 정한다.
여러 개 매치되거나(인자로 찾은 경우) 진행 중 표에 행이 여러 개거나 하나도 없으면
사용자에게 어느 spec인지 확인한다 — 확인이 끝날 때까지 호출한 커맨드는 다음 단계로
진행하지 않는다.

## 2. 브랜치 확인

확정된 spec의 spec.md 상단 **상태**가 `done`이 아니면, 현재 git 브랜치 이름에
`US-NN-`이 포함되는지 확인한다(`/spec-new`가 `<type>/US-NN-<slug>`로 만든 전용
브랜치). 포함돼 있지 않으면 여기서 멈추고 해당 브랜치로 전환하라고 안내한다 — 다른
spec의 브랜치나 `main`에서 이어서 진행하면 이 spec과 무관한 브랜치에서 작업(파일 작성,
코드 작성, 검증/AC 체크박스 갱신 등 호출한 커맨드가 하는 일)이 이뤄진다.

## 반환

확정된 spec 폴더 경로. 위 두 조건(폴더 유일성, 브랜치 일치) 중 하나라도 걸려 멈췄다면
호출한 커맨드는 이후 단계로 진행하지 않는다.
