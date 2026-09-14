---
name: traceability
description: prd/design 문서와 spec.md 간 링크 포맷, spec 폴더 내 파일 간 추적성 규칙. spec.md/design 문서의 설계 링크를 쓰거나, `/spec-validate`에서 그 링크의 유효성을 확인할 때 사용.
---

# Traceability — PRD ↔ 설계 ↔ spec 폴더

목적: 파일 상단 링크만 보고 요건-설계-구현을 추적할 수 있게 한다.

```
prd.md (§N, 고정 앵커) ← docs/internal/design/*.md ← specs/US-NN-<slug>/{spec.md, design.md, task.md}
```

**용어 주의**: `docs/internal/design/*.md`(토픽별 설계 문서, 아래에서 "design 문서")와
`specs/US-NN-<slug>/design.md`(spec 전용 구현 설계, designer가 작성)는 이름이 비슷하지만
다른 파일이다. 아래 규칙의 "design 문서"는 항상 전자를 가리킨다.

## 필수 규칙

- design 문서를 쓰거나 고칠 때: `# 제목` 바로 다음 줄에 `> 요건: [prd.md §N](...)`을
  남겨라. 대응 PRD 섹션이 없는 순수 기술 문서면 생략해도 된다.
- spec.md를 쓸 때: 상단에 `> 설계:` 링크로 관련 design 문서를 연결하라. 관련 design
  문서가 없으면 그 줄 자체를 넣지 마라.

## `/spec-validate`에서 AC 전수 통과 시 실행할 것

- [ ] spec.md/design.md의 설계 링크가 실제로 존재하는 문서를 가리키는지 확인하라.
