---
name: architecture
description: spec.md/design.md 작성 시 레이어 구조·의존성 방향과 모순되지 않는지 확인할 때 사용. analyst·designer 전용, implementer는 사용하지 않음.
---

# Architecture (요약)

전체 내용은 `docs/internal/architecture/`(README/application/technical/runtime) +
`docs/internal/design/data-schema.md`에 있다 — 이 스킬은 그 문서들을 대체하지 않고, 매번
전체를 다시 읽지 않도록 자주 쓰는 핵심만 압축한다. 모호하면 원본 문서를 직접 읽는다.

## 레이어 (상위 → 하위, 역방향 참조 금지)

```
CLI → API → Pipeline/Query → Infra
```

| 레이어 | 위치 | 책임 |
|---|---|---|
| API | `src/api/` | HTTP 계약, 요청 검증, 에러 매핑 |
| Pipeline | `src/pipeline/steps/` | 순수 함수, 문서 처리 |
| Query | `src/query/` | 검색·병합·리랭킹 |
| Infra | `src/infra/` | 외부 저장소 CRUD (s3/redis/qdrant/postgres) |

## 호출자별 사용법

- **analyst**: README.md 개요 + `data-schema.md`만 훑어 요청이 기존 구조/스키마와
  모순되는지만 판단한다. 모순이 있으면 spec.md를 쓰기 전에 먼저 보고한다.
- **designer**: 위 레이어 표와 의존성 방향을 기준으로, design.md에 "이 작업이 어느 레이어의
  어느 파일을 건드리는지, 역방향 참조가 생기지 않는지"를 명시적으로 적는다. 더 필요하면
  `application.md` §1(레이어)·§2(의존성)·§6(프로젝트 구조)를 직접 읽는다. §3·4·5(예외 처리/
  로깅/설정)는 `exception-handling`/`logging` 스킬이 다루므로 여기서 다시 읽지 않는다.

**implementer는 이 스킬을 쓰지 않는다** — designer가 design.md에 이미 적어둔 레이어/파일
결정을 그대로 따르면 된다. 이 결정이 맞는지는 validator가 완료 기준 검증 시 이 스킬을
기준으로 다시 확인한다(design.md의 레이어 판단 오류를 뒤에서 걸러내는 역할).
