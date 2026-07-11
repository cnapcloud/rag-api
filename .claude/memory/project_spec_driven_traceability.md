# Spec-driven traceability system (2026-07-12)

rag-api를 스펙 중심 개발체계로 전환하는 논의 끝에, 기존 산출물(backlog/plan/docs)의
이름·위치는 그대로 두고 링크 규칙만 표준화하기로 결정했다.

## 4단 체계

```
docs/internal/prd.md (§1~§N, 고정 앵커 — 별도 ID 불필요)
   ↑ design 문서 2번째 줄: "> 요건: prd.md §N"
docs/internal/design/*.md
   - 다중 backlog가 나눠 구현하는 영역은 자체 하위요건 테이블 유지 (dedup.md의 D-XX,
     multi-source-ingest.md의 R-XX) — 테이블에 `US` 컬럼 추가해 크로스워크
   - 단순 영역은 최하단 "변경 이력" 표만
   ↑ backlog 2번째 줄: "> 설계: design/xxx.md (로컬 ID)"
.claude/backlogs/US-XX-*.md  ↔ (번호+슬러그 완전 일치)  .claude/plans/XX-*.md
```

전체 규칙: `.claude/rules/conventions/07-traceability.md`. backlog 신규 작성 템플릿:
`.claude/backlogs/_TEMPLATE.md` (rag-ent-api의 E-XX 패턴 참고 — `**상태**` 인라인,
`완료 기준` 체크박스화, `의존성` 섹션 신설).

## 결정 이유

- design 문서가 코드와 따로 노는 근본 원인은 "갱신을 강제하는 지점이 없어서"였음 —
  plan의 완료 기준에 "design 문서 갱신"을 표준 체크리스트 항목으로 넣어 해결.
- D-XX/R-XX 같은 로컬 하위요건 ID 체계는 이미 자연발생적으로 잘 작동 중이라 폐기하지
  않고 US 컬럼만 추가(B안) — 새 ID 체계를 얹는 것보다 정보 손실이 없음.
- plan 파일이 backlog 안에 이미 충분한 설계 상세를 담고 있으면(예: US-35의 SQL/설정값)
  별도 plan 작성을 강제하지 않고 `plan.md`에 `통합(backlog 참고)`로 표기하는 예외를 둠 —
  중복 문서화 방지.

## 발견한 버그

`.claude/rules/conventions/00-progress-tracking.md`가 `docs/dev/architecture.md`,
`docs/dev/data-schema.md`를 참조하고 있었는데 실제 경로는 `docs/internal/architecture.md`,
`docs/internal/design/data-schema.md`. 세션 시작 규칙을 그대로 따라도 문서를 못 찾는
상태였음 — 수정 완료.

## 적용 범위 (2026-07-12 기준)

파일럿으로 dedup 영역만 완전 적용: `dedup.md` + US-23/US-24/US-35.
나머지 26개 backlog, `multi-source-ingest.md`의 R-표, plans/03·04 번호 정정(실제로는
US-05/US-06을 커버하는데 파일명이 03/04로 남아있음), US-01/08/13 slug 불일치는
**미소급** — 새 항목부터 적용하고, 기존 파일은 다음에 수정할 일이 생기면 그때 맞춘다.
전체 소급이 필요하면 이 파일과 `07-traceability.md`를 같이 참고해서 진행.
