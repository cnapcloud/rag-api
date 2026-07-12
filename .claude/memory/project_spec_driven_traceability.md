---
name: project-spec-driven-traceability
description: 스펙 추적성 체계(prd/design/backlog/plan) 적용 범위 — dedup 영역만 파일럿, 나머지 미소급
metadata:
  node_type: memory
  type: project
---

전체 규칙은 `.claude/rules/conventions/07-traceability.md`에 있음 (2026-07-12 동일자에
`00-progress-tracking.md`와 합쳤다가 문서 크기/읽는 빈도가 달라 다시 분리됨 — 세션마다 읽는
북키핑은 00, backlog/design 작성 시에만 읽는 링크 포맷 상세는 07). 여기는 규칙 자체가 아니라
**적용 범위(2026-07-12 기준)**만 기록.

파일럿으로 dedup 영역만 완전 적용: `dedup.md` + US-23/US-24/US-35.
나머지 26개 backlog, `multi-source-ingest.md`의 R-표, plans/03·04 번호 정정(실제로는
US-05/US-06을 커버하는데 파일명이 03/04로 남아있음), US-01/08/13 slug 불일치는
**미소급** — 새 항목부터 적용하고, 기존 파일은 다음에 수정할 일이 생기면 그때 맞춘다.

**Why:** 규칙 문서(07-traceability.md)는 코드베이스에 체크인되어 항상 최신이지만, "어디까지
실제로 적용됐는지"는 규칙 문서만 봐서는 알 수 없음 — 소급 여부를 매번 다시 확인하지 않기 위해 기록.

**How to apply:** dedup 외 영역의 backlog/plan을 작업할 때 traceability 링크가 없어도 버그가
아님 — 미소급 대상이라 그런 것. 전체 소급 작업을 하게 되면 이 메모리는 삭제할 것.
