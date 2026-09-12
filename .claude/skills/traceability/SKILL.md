---
name: traceability
description: prd/design 문서와 spec.md 간 링크 포맷, spec 폴더 내 파일 간 추적성 규칙. spec.md의 설계 링크를 쓸 때, 또는 spec 상태를 done으로 전환할 때 사용.
---

# Traceability — PRD ↔ 설계 ↔ spec 폴더

목적: 파일 상단 링크만 보고 요건-설계-구현을 추적할 수 있게 한다.

```
prd.md (§N, 고정 앵커) ← docs/internal/design/*.md ← specs/US-NN-<slug>/{spec.md, design.md, task.md}
```

**용어 주의**: `docs/internal/design/*.md`(토픽별 설계 문서, 이 스킬에서 "design 문서"라고
부르는 것)와 `specs/US-NN-<slug>/design.md`(이 spec 전용 구현 설계, designer가 작성)는
이름이 비슷하지만 다른 파일이다. 아래 규칙에서 "design 문서"는 항상 전자를 가리킨다.

기존 `backlogs/`+`plans/`처럼 별도 인덱스 두 개의 번호를 맞추던 방식은 spec 폴더 구조에서는
불필요하다 — spec.md/design.md/task.md가 같은 폴더에 있으므로 번호가 항상 일치한다.

## 필수 규칙

- **design 문서 → prd 링크**: design 문서(`docs/internal/design/*.md`) `# 제목` 바로
  다음 줄에 `> 요건: [prd.md §N](...)`을 남긴다. 대응되는 PRD 섹션이 없는 순수 기술
  문서는 생략 가능.
- **spec.md 상단 `> 설계:` 링크**: 관련 design 문서가 있으면 반드시 연결한다. 없으면
  그 줄 자체를 생략한다.
- **design 표의 US 컬럼**: 하나의 design 문서를 여러 spec이 나눠 구현하면, 문서 안 하위요건
  표에 US 컬럼을 추가해 어떤 spec(US-NN)이 구현했는지 표시한다.

## `done` 전환 시 확인

- [ ] design 표(US 컬럼) 또는 변경 이력에 이번 작업 반영
- [ ] `.claude/specs/index.md`의 해당 행 status를 spec.md **상태**와 동일하게 동기화
- [ ] spec.md/design.md(spec 폴더 안의 구현 설계)의 설계 링크가 실제로 존재하는 문서를
      가리키는지 확인

기존 `backlogs/`+`plans/`(US-01~52)는 `specs/US-NN-*/`로 전량 이관 완료됐다 — 이제 이
스킬이 모든 spec에 적용된다(과거처럼 신규 항목에만 적용되는 예외 없음). US-01~52는
`plan.md` 시절 산출물이라 `design.md`/`task.md` 분리 이전 형식으로 남아 있다 — 과거
기록으로 두고 소급 이관하지 않는다.
