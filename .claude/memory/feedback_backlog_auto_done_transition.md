---
name: feedback_backlog_auto_done_transition
description: Auto-transition backlog status to done and move file out of todo/ once all completion criteria are met, without asking first
metadata:
  type: feedback
---

구현 + 관련 테스트가 끝나고 backlog 항목의 완료 기준(체크박스)이 전부 충족되면, 사용자에게
물어보지 않고 바로 `.claude/rules/conventions/00-progress-tracking.md` §4의 done 전환 절차를
직접 실행한다: 상태를 `done`으로 바꾸고, `backlogs/todo/US-XX-*.md` → `backlogs/US-XX-*.md`로
파일을 옮기고, `backlog.md` 링크에서 `todo/` 접두사를 제거한다.

**Why**: 2026-07-13 US-37 작업 중 "구현/테스트 완료 후 상태 갱신 + todo에서 꺼내는 걸 왜
자동으로 안 하냐"는 질문을 받음 — 룰 자체는 이미 있었지만(00-progress-tracking.md §4)
매번 확인을 구하고 있었음. 사용자가 "앞으로 해줘,, 직접"이라고 명시적으로 확인 절차 생략을
요청함.

**How to apply**: 완료 기준 중 사용자의 수동 확인(엔드투엔드 브라우저 테스트 등)이 필요한
항목이 있으면 그건 당연히 사용자가 직접 체크할 때까지 기다려야 하지만, 그 외 자동으로 검증
가능한 항목(단위 테스트 통과 등)은 확인되는 즉시 체크하고, 전체가 다 체크된 시점에 상태
전환/파일 이동까지 한 번에 처리한다. `plans/plan.md`에 해당 backlog 행이 없으면 같이
추가한다(`07-traceability.md`).
