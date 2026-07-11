# Traceability — PRD ↔ 설계 ↔ backlog ↔ plan

목적: 파일명·파일 상단 몇 줄만 보고 요건-설계-구현 사이를 추적할 수 있게 한다.
본문을 전부 읽어야 연결 관계를 알 수 있는 상태를 금지한다.

---

## 4단 체계

```
docs/internal/prd.md (§1~§N, 고정 앵커)
   ↑ design 문서 상단 고정 링크
docs/internal/design/*.md
   ↑ backlog 상단 고정 링크
.claude/backlogs/US-XX-*.md  ↔ (번호+슬러그 일치)  .claude/plans/XX-*.md
```

`prd.md`는 섹션 번호(`## 10. 중복 문서 감지`)가 이미 안정적인 앵커이므로 별도 ID 체계를 추가하지 않는다.

---

## 1. design 문서 → prd.md 링크

각 design 문서의 `# 제목` 바로 다음 줄에 고정 포맷으로 추가한다. 여러 섹션에 걸치면 모두 나열.

```markdown
# 문서 중복·갱신 감지 파이프라인 디자인

> 요건: [prd.md §10](../prd.md#10-중복-문서-감지-dedup)

## 1. 개요
```

PRD의 특정 섹션과 대응되지 않는 순수 기술 설계 문서(예: `system-flows.md`, `data-schema.md`)는 생략 가능.

## 2. design 문서 내부 하위요건 테이블

`dedup.md`(D-XX), `multi-source-ingest.md`(R-XX)처럼 하나의 design 문서를 여러 backlog가
나눠서 구현하는 경우, 문서 안에 자체 하위요건 테이블(로컬 ID)을 유지한다. 새로 만들 필요는 없고,
기존 테이블에 **`US` 컬럼을 추가**해 어떤 backlog가 그 항목을 구현했는지 명시한다.

```markdown
| ID | Title | Status | US |
|---|---|---|---|
| D-04 | 3단계: 청크 단위 임베딩 비교 | done | US-35 |
```

하위요건 테이블이 없는 단순 design 문서(한두 개의 backlog만 관련)는 대신 문서 최하단에
"변경 이력" 표만 둔다.

```markdown
## 변경 이력

| US | 내용 |
|----|------|
| US-36 | HTMLCleanReader를 trafilatura 밀도 기반 추출로 교체 |
```

## 3. backlog → design 링크

`# US-XX: 제목` 바로 다음 줄에 고정 포맷. 로컬 ID가 있으면 괄호로 병기.

```markdown
# US-35: Dedup Stage 3 — 청크 단위 임베딩 비교 (chunk_compare) + 임계값 기반 body 확정

> 설계: [dedup.md](../../docs/internal/design/dedup.md) (D-04)
```

관련 design 문서가 없으면 `> 설계: 없음 — 본 plan에서 docs/internal/design/<신규>.md 작성`.

## 4. backlog ↔ plan 파일명

- plan 번호는 US 번호와 반드시 동일 (기존 `00-progress-tracking.md` 규칙 유지)
- **plan 슬러그는 backlog 슬러그와 완전히 동일** (신규 — 지금까지 미준수)
- 예외: backlog 본문에 이미 설계 상세(스키마, 알고리즘, 설정값 등)가 충분히 포함되어 있어
  별도 plan이 실질적으로 중복인 경우, plan 파일을 생략하고 `plans/plan.md` 인덱스에
  `통합(backlog 참고)`로 표기한다. 임의로 판단하지 말고 예외 적용 시 이유를 인덱스 옆에 남긴다.

## 5. 파일명 키워드 정렬

backlog/plan 슬러그에는 관련 design 문서 파일명의 핵심 키워드를 포함한다
(`US-35-dedup-stage3-chunk-compare.md` ↔ `design/dedup.md`).
`ls .claude/backlogs | grep <키워드>`, `ls docs/internal/design | grep <키워드>`로
서로 찾아질 수 있어야 한다.

---

## 6. backlog 파일 템플릿

새 backlog 항목은 `.claude/backlogs/_TEMPLATE.md`를 기준으로 작성한다 (rag-ent-api E-XX 패턴을
rag-api 컨벤션에 맞춘 것). 핵심 추가 요소:

- `**상태**: todo|in-progress|done|blocked` — 제목 바로 아래 인라인. `backlog.md` 인덱스의 Status
  컬럼과 항상 동기화(둘 다 갱신, 한쪽만 바꾸고 끝내지 않는다).
- `완료 기준`은 체크박스(`- [ ]`/`- [x]`)로 작성 — 뭉뚱그린 문장이 아니라 테스트 케이스/수동 확인과
  1:1 대응되게 쪼갠다.
- `의존성` 섹션 — 선행되어야 하는 다른 US를 명시. design 문서의 하위요건 테이블(D-XX/R-XX)에
  이미 `Depends on` 컬럼이 있으면 그걸 US 단위로 환산해서 적는다. 없으면 "없음".

## 완료 기준 체크리스트 (plan에 포함)

새 기능/버그 수정이 design 문서와 관련되면 plan의 완료 기준에 다음을 포함한다.

- [ ] backlog 2번째 줄에 `> 설계: ...` 링크 추가/확인
- [ ] design 문서의 하위요건 테이블(US 컬럼) 또는 변경 이력 표 갱신
- [ ] design 문서 자체가 코드와 어긋난 부분이 있으면 본문도 함께 갱신
- [ ] 범위가 prd.md 요건 자체를 바꾸면 prd.md도 함께 갱신
