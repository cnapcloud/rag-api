# 스펙 기반 AI 개발 가이드

이 프로젝트는 설계 이후의 작업(spec.md 작성 → 구현 설계 → 작업 분리/구현 → 코드 생성 →
검증)을 `analyst`/`designer`/`implementer`/`validator` 서브에이전트가 단계별로 초안을
만들고, 개발자는 `/spec-new`·`/spec-design`·`/spec-implement`·`/spec-validate` 커맨드로
각 단계를 호출·검토하는 방식으로 진행한다 — 기능/버그 수정을 코드부터 시작하지 않는다.
요건(prd) → 설계(design 문서) → 작업 단위(spec.md) → 구현 설계+작업 분리(design.md/
task.md) → 코드 → 검증 순으로 이어지는 스펙 체계를 따르고, 각 단계는 문서 상단의 고정된
링크로 서로 연결되어 있어야 한다. 목적은 "왜 이렇게 만들었는지"를 나중에(다른 개발자든
AI든) 코드만 보고는 알 수 없을 때, 문서를 몇 단계만 거슬러 올라가면 찾을 수 있게 하는
것이고, 동시에 AI가 만든 산출물을 개발자가 무엇을 기준으로 검토해야 하는지를 명확히 하는
것이다.

```
docs/internal/requirement/prd.md   요건 (섹션 번호가 앵커, 예: §10)
   ↑
docs/internal/design/*.md          설계 (토픽별, 개발자가 작성)
   ↑
.claude/specs/US-NN-<slug>/        spec.md ↔ design.md(이 spec 전용 구현 설계) ↔ task.md
```

**용어 주의**: `docs/internal/design/*.md`(토픽별 설계 문서)와 spec 폴더 안의
`design.md`(이 spec 전용 구현 설계, designer가 작성)는 이름이 비슷하지만 다른 파일이다.
아래에서 그냥 "design 문서"라고 하면 전자, "design.md"라고 구체적으로 지칭하면 후자다.

## 진행 방식 — 개발자 ↔ AI

설계까지는 개발자가 담당하고, 그 이후(spec.md → design.md/task.md → 코드 → 검증)는 각
단계 전용 서브에이전트가 초안을 만든다. 승인 게이트는 spec.md 단계 하나뿐이지만, 나머지 단계도
문제가 생기면 커맨드가 자동으로 다음 단계로 넘어가지 않고 개발자 판단을 기다린다.

1. **설계** — 개발자가 `docs/internal/design/*.md`를 작성/수정한다.
2. **개발 항목 도출** — 새 아티팩트를 만들 필요 없이, 설계 문서 안의 하위요건 테이블(D-XX/R-XX,
   "설계 문서 작성/수정" 절 참고)의 각 행이 곧 도출된 항목이다. 여러 spec이 하나의 표를
   나눠서 구현한다.
3. **`/spec-new [feature|bugfix|patch:] <요청 설명>` → 승인** — 커맨드가 먼저 브랜치를
   준비한다: `main`(클린 트리)에서만 시작할 수 있고, 타입 프리픽스(생략 시 `feature`)로
   `<type>/US-NN-<slug>` 전용 브랜치를 새로 만든다 — `patch`는 spec 작업 공간이 아니라
   임시 작업용으로만 남는다. 그 위에서 `analyst`가 번호를 채번받은
   `.claude/specs/US-NN-<slug>/` 폴더에 `spec.md`를 작성한다(요청 원문, F1/F2... 세부
   기능별로 AC ID가 붙은 완료 기준). 개발자는 "spec.md 리뷰 시 확인할 것" 절 기준으로
   검토하고, 승인하면 커맨드가 `## 승인` 체크박스를 직접 `[x]`로 바꾼다 — `analyst`는
   스스로 체크하지 않는다(셀프 승인 금지). **승인 전에는 다음 단계로 넘어가지 않는다.**
4. **`/spec-design`** — `designer`가 승인된 spec.md를 바탕으로 `design.md`(아키텍처 개요,
   영향 레이어/파일, 해당 시 API 계약/데이터 모델/에러 모델/로깅/NFR, 리스크&롤백)를 쓰고,
   이어서 `task.md`(vertical slice 단위 task 목록 + task별 구현 방법)를 쓴다 — task.md는
   더 이상 선택이 아니라 항상 만든다(완료 기준이 1개뿐이어도 최소 1개 task). spec.md의 모든
   AC가 어느 task에 매핑되는지 커버리지까지 확인한다. 둘 다 별도 승인 체크박스가 없어
   필수 게이트는 아니지만, 검토를 원하면 이 시점에 한다.
5. **`/spec-implement`** — `implementer`가 task 단위로 순회하며 구현+테스트를 진행한다.
   이슈 없이 통과하면 자동으로 다음 항목으로 넘어가고, design.md/task.md 설계 결함 등
   이슈를 만나면 그 자리에서 멈춰 개발자 판단을 요청한다(상태가 `blocked`로 바뀐다).
6. **`/spec-validate`** — `validator`가 spec.md의 모든 완료 기준(AC)을 실제로 테스트/수동
   확인으로 검증하고, `design.md`의 레이어/파일 판단도 architecture 기준으로 재검증한다.
   전체 통과하면 **개발자 확인 없이 자동으로** spec.md 상단 **상태**를 `done`으로 바꾸고
   `.claude/specs/index.md`를 History로 옮긴다 — 옛 방식처럼 체크리스트를 개발자가 매번
   수동으로 훑을 필요가 없다. 일부 실패하면 유형(구현 문제 vs 설계 문제)에 따라
   `/spec-implement` 또는 `/spec-design`을 다시 실행한다.

## 새 작업을 시작하기 전에

1. `main` 브랜치로 전환하고 커밋 안 된 변경이 없는지 확인한다 — `/spec-new`가 `main`이
   아닌 브랜치에서는 거부하고, 작업 트리가 지저분하면 먼저 커밋/스태시하라고 안내한다.
2. `.claude/specs/index.md`를 열어 "진행 중" 표(+ "마지막 채번 번호" 필드)로 이미 진행
   중이거나 완료된 작업이 있는지 확인한다.
3. 관련된 `docs/internal/design/*.md` 문서를 읽고, 기존 설계와 충돌하지 않는지 확인한다
   (`analyst`가 `architecture` 스킬로 자동 확인하지만, 개발자도 요청 시점에 한 번 더 본다).
   새 기능이 기존 설계를 바꾼다면 이번 작업 범위에 설계 문서 갱신도 포함시킨다.

## spec.md(US) 리뷰 시 확인할 것

`/spec-new` 3단계에서 `analyst`가 초안을 만들면, 승인(`## 승인` 체크박스를 `[x]`로 바꾸기)
전에 아래를 확인한다.

- `.claude/templates/spec.md` 형식을 따랐는지 — 자유 형식이면 반려.
- 제목 바로 다음 줄에 관련 (토픽) design 문서 링크 `> 설계: [data-schema.md](...)` 같은
  형식이 있는지. 관련 문서가 아직 없다면 이번 작업 범위에서 새로 썼는지.
- 세부 기능(F1, F2, ...)마다 완료 기준이 뭉뚱그린 문장이 아니라, 실제 테스트 케이스/수동
  확인 항목과 하나씩 대응되는 체크박스로 쪼개졌고 `F1-1`/`F1-2`/`C1` 같은 AC ID가 붙어
  있는지 — 이 ID는 이후 `design.md`/`task.md`/`validator`가 그대로 재사용하므로 한 번
  붙이면 재번호를 매기지 않는다.

design.md/task.md는 spec.md와 같은 폴더 안에 있으므로(구식 방식처럼 별도 번호/
슬러그를 맞출 필요가 없다) 이 시점엔 확인할 것이 없다 — `/spec-design` 단계에서 둘 다
항상 만들어진다(생략 옵션 없음).

## 설계 문서 작성/수정

- 제목 바로 다음 줄에 관련 요건 링크를 남긴다: `> 요건: [prd.md §N](...)`.
  prd의 특정 섹션과 대응되지 않는 순수 기술 문서(인프라 구조 설명 등)는 생략해도 된다.
- 여러 작업 단위가 하나의 설계 문서를 나눠서 구현하는 경우, 문서 안에 하위요건 테이블을 두고
  각 행에 `US` 컬럼으로 어떤 spec(US-NN)이 그 부분을 구현했는지 표시한다. 링크 포맷 상세는
  `.claude/skills/traceability/SKILL.md` 참고.

## `done` 전환 — validator가 자동 확인하는 것

`/spec-validate`가 전체 AC 통과로 판정하면 커맨드가 곧바로 아래를 처리한다(개발자가 매번
수동으로 훑던 옛 체크리스트를 자동화한 것 — `.claude/skills/traceability/SKILL.md`의
"`done` 전환 시 확인" 항목과 동일):

- design 문서(`docs/internal/design/*.md`)의 하위요건 표(US 컬럼) 또는 변경 이력에 이번
  작업 반영
- spec.md/design.md(spec 폴더 안의 구현 설계)의 설계 링크가 실제로 존재하는 문서를
  가리키는지 확인
- `.claude/specs/index.md`에서 해당 행을 "진행 중"→"History"로 이동
- spec.md 상단 **상태**를 `done`으로 갱신

구현 중 설계와 다르게 만든 부분이 있으면 design 문서 본문도, 요건 자체가 바뀌었다면
`prd.md`도 별도로(자동화 범위 밖) 함께 갱신해야 한다 — 이건 validator가 판단할 수 없는
개발자/설계자의 몫이다. `validator`가 남긴 `test_result.md`로 AC별 검증 방법과 결과를
확인할 수 있다.

## 그 밖의 코딩 컨벤션

import 경로, 예외 처리, 로깅, 설정/infra/테스트 컨벤션은 `CLAUDE.md`의 "하드 룰"과
`.claude/skills/`(`conventions`, `import-paths`, `exception-handling`, `logging`)를
참고한다 — `implementer`는 이 스킬들을 자동으로 로드하지만, 개발자가 직접 구현할 때도
동일하게 적용된다.

이 문서는 개발자가 새 작업을 시작하기 전에 직접 읽고 그 절차에 따라 `/spec-*` 커맨드를
단계별로 실행하는 진입 문서이며, `CLAUDE.md`와 달리 AI 세션에 자동으로 로드되지 않는다.
