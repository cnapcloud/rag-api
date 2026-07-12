# Traceability — PRD ↔ 설계 ↔ backlog ↔ plan

목적: 파일명·파일 상단 링크만 보고 요건-설계-구현을 추적할 수 있게 한다. design/backlog/plan
문서를 작성하거나 backlog를 `done`으로 전환할 때만 참고한다 — 세션마다 읽는 짧은 북키핑 규칙은
`00-progress-tracking.md`에 있다.

```
prd.md (§N, 고정 앵커) ← design/*.md ← backlogs/US-XX-*.md ↔ plans/XX-*.md (번호 일치)
```

## 필수 규칙

- **design → prd 링크**: design 문서 `# 제목` 바로 다음 줄에 `> 요건: [prd.md §N](...)`을
  남긴다. PRD 특정 섹션과 대응되지 않는 순수 기술 문서는 생략 가능.
- **design 표의 US 컬럼**: 하나의 design 문서를 여러 backlog가 나눠 구현하면(`dedup.md`의
  D-XX처럼), 문서 안 하위요건 표에 `US` 컬럼을 추가해 어떤 backlog가 구현했는지 표시한다.
  실제 예시는 `dedup.md` 참고.
- **backlog 템플릿**: 신규 backlog는 반드시 `.claude/backlogs/_TEMPLATE.md` 형식으로 작성한다
  (자유 서술 금지). 설계 링크·상태 동기화·완료 기준 작성법은 템플릿 하단 "작성 규칙" 참고.
- **plan 번호 = backlog 번호**: `US-08` → `08-<slug>.md`. backlog 본문에 이미 구현 상세가
  충분해 plan이 사실상 중복이면 파일을 생략하고 `plans/plan.md`에 `통합(backlog 참고)`로
  표기한다. 2026-07-12 이전 파일(예: `04-zombie-detection-to-sensor.md`는 실제로 US-06을
  커버)은 소급 리네임하지 않는다 — 이 규칙은 그 이후 신규 plan 파일부터 적용.
- plan 파일을 만들면 같은 세션에 `plans/plan.md`에 행을 추가한다.

## `done` 전환 시 확인

- [ ] design 표(US 컬럼) 또는 변경 이력에 이번 작업 반영
- [ ] `plans/plan.md`에 해당 행 확인 — 없으면 추가
