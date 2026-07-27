# Progress Tracking

목적: `.claude/backlogs/backlog.md` / `.claude/plans/plan.md` 인덱스로 현재 진행 상황을 파악하고
최신 상태로 유지하기 위한 규칙. 세션마다 참고하는 짧은 북키핑 규칙만 담는다 — 문서 간 링크
포맷 등 실제로 backlog/design 문서를 작성할 때만 필요한 상세 규칙은
`07-traceability.md`에 있다.

## 1. Index Files

`.claude/backlogs/backlog.md`는 전체 user story(ID, 제목, 상태)를, `.claude/plans/plan.md`는 전체
구현 계획(계획 번호, 제목, 대상 US, 상태)을 담는다. 기능 구현, 버그 수정, 신규 작업 계획이 있는
모든 세션 시작 시 두 인덱스 파일을 읽는다 — 개별 상세 파일을 열지 않아도 완료/대기 상태를 바로
파악할 수 있다.

두 파일을 함께 읽을 때 같은 US를 가리키는 행의 status가 서로 다르면(예: backlog는 `done`인데
plan은 `todo`, 또는 plan이 링크한 파일이 존재하지 않으면) 즉시 사용자에게 보고하고
`07-traceability.md`의 done 전환 체크리스트에 따라 바로잡는다 — 다음 세션까지 방치하지 않는다.

## 2. Reference Documents

새 backlog 항목이나 구현 계획을 작성하기 전에, 기존 아키텍처·데이터 모델과 어긋나지 않는지
`docs/internal/architecture/README.md`(시스템 아키텍처 인덱스 — 같은 폴더의 `application.md`,
`technical.md`, `runtime.md` 포함)와 `docs/internal/design/data-schema.md`(Qdrant PointStruct
payload, Postgres/Redis 필드)를 읽는다. 이 문서들은 현재 시스템 상태를 나타내므로 backlog/plan이
여기 명시된 내용과 모순되거나 중복되면 안 된다. 새 기능이 스키마를 바꾸면 구현과 함께 이 문서도
갱신한다.

## 3. Status Values

상태값은 `todo`(미시작) / `in-progress`(현재 또는 최근 세션에서 작업 중) / `done`(구현 및 테스트
완료) / `blocked`(의존성 또는 결정 필요로 진행 불가) 중 하나를 사용한다.

## 4. When to Update

작업을 시작하면 `in-progress`로, 구현과 테스트가 끝나면 `done`으로 상태를 바꾼다. `done`으로
전환하기 전에는 별도 plan 파일이 없는 `통합(backlog 참고)` 케이스라도 `07-traceability.md`의
done 전환 체크리스트를 반드시 거친다. 완료 기준이 충족되면 사용자 확인 없이 바로 `done`으로
전환해도 되지만, 이는 확인 절차만 생략하는 것이지 체크리스트 단계(plan.md status 동기화,
링크 무결성 확인 등)를 생략해도 된다는 뜻이 아니다 — 자동 전환이든 아니든 체크리스트는
동일하게 전부 거친다. `done`으로 바뀌는 시점에 상세 파일을
`backlogs/todo/US-XX-*.md`에서 `backlogs/US-XX-*.md`로 옮기고, `backlog.md`의 링크에서 `todo/`
접두사를 제거한다.

새 backlog 항목(US-XX)이나 plan 파일을 만들면 해당 인덱스에 새 행을 추가한다. 신규 backlog
항목은 반드시 `.claude/backlogs/_TEMPLATE.md` 형식을 따라야 하며(옛 방식으로 새로 만드는 것은
금지), plan 파일명 규칙은 `07-traceability.md`를 참고한다.

상태가 실제 진행 상황과 어긋난 채로 세션을 끝내지 않는다 — 행이 `todo`인데 이미 작업이 끝났다면
세션 종료 전에 바로잡는다.

## 5. 신규 Backlog 생성 워크플로우

사용자가 "백로그 만들어" 같은 요청을 하면 아래 순서를 그대로 지킨다 — 단계를 건너뛰거나
순서를 바꿔 바로 구현으로 넘어가지 않는다.

1. **생성**: `.claude/backlogs/_TEMPLATE.md` 형식으로 처음부터 `.claude/backlogs/todo/US-XX-*.md`에
   작성한다(상태 `todo`). 루트(`backlogs/US-XX-*.md`)에 만들지 않는다 — 그 자리는 `done` 전환
   때만 쓴다. `backlog.md` 인덱스에도 `todo/` 접두사를 포함해 링크를 추가한다.
2. **리뷰 요청**: 목적/범위/비범위/완료 기준을 사용자에게 검토받는다. 백로그를 만들자마자
   바로 코딩을 시작하지 않는다 — 이 단계가 실제 구현 전 마지막 확인 지점이다.
3. **승인 후 계획 수립**: 사용자 승인을 받으면 상태를 `in-progress`로 바꾸고 `plans/plan.md`에
   행을 추가한다(구현 상세가 backlog에 이미 충분하면 `통합(backlog 참고)`, 아니면
   `plans/XX-*.md` 별도 파일 — `07-traceability.md` 참고).
4. **구현** → **테스트 작성/실행** → **테스트 검증**(실패가 남아있으면 다음 단계로 넘어가지
   않는다).
5. **완료 처리**: 상태를 `done`으로 바꾸고, 파일을 `todo/`에서 `backlogs/`로 옮기고,
   `backlog.md` 링크에서 `todo/` 접두사를 제거하고, `plan.md` 상태도 `done`으로 갱신한다.
   `07-traceability.md`의 done 전환 체크리스트도 함께 확인한다.
