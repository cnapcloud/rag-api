# US-38: WebConnector Admin UI — seed page 포함 / unrestricted 체크박스 노출

**상태**: done

## 목적

[US-37](US-37-web-connector-unrestricted-scope.md)에서 백엔드에 추가하는 `unrestricted`
옵션과, 이미 존재하지만 지금까지 Admin UI에 노출된 적 없는 `skip_seed_pages` 옵션을 Web
커넥터 Create/Edit 모달에 노출한다. 이 UI가 없으면 두 필드 모두 API를 직접 호출해야만 설정
가능하다.

## 범위

- 저장소: `rag-admin`, 파일: `src/components/connector/ConnectorModal.tsx`, Web 타입
  `ConfigFields()`([ConnectorModal.tsx:275-337](../../../rag-admin/src/components/connector/ConnectorModal.tsx#L275-L337)).
- 체크박스 2개를 Seed URLs 입력 바로 아래, Exclude Patterns보다 위에 추가:
  1. **"Include seed page as a document"** — 기존 백엔드 필드 `skip_seed_pages`(기본
     `true`)를 노출. checked = `skip_seed_pages: false`.
  2. **"Unrestricted"** — US-37에서 추가되는 `unrestricted`(기본 `false`).
  - 설명 문구는 상시 노출 텍스트가 아니라 라벨 옆 info 아이콘의 hover 툴팁으로 처리(폼을
    간결하게 유지하기 위함, 인라인 헬퍼 텍스트는 지양).
- `buildConfig()`/`flattenConfig()`([ConnectorModal.tsx:386-447](../../../rag-admin/src/components/connector/ConnectorModal.tsx#L386-L447))에
  두 키 반영. `Create`/`Edit` 모달이 `ConfigFields`를 공유하므로 한 곳만 고치면 양쪽에 반영됨.

### 확정 레이아웃 (mockup)

```
Seed URLs * (one per line)
┌───────────────────────────────────────────────────────────────┐
│ https://namu.wiki/w/고양이                                       │
└───────────────────────────────────────────────────────────────┘
☐ Include seed page as a document ⓘ
☐ Unrestricted ⓘ
  (ⓘ = hover tooltip, full sentence not shown inline)

Exclude Patterns (optional, one per line)
┌───────────────────────────────────────────────────────────────┐
│ */blog/*                                                        │
└───────────────────────────────────────────────────────────────┘

Depth          Max Pages       Min Content Chars
┌────────┐     ┌────────┐      ┌────────┐
│ 2       │     │ 50      │      │ 200     │
└────────┘     └────────┘      └────────┘
```

Tooltip 문구:
- Include seed page: `When unchecked, seed URLs are only used to discover links and are not
  saved as documents.`
- Unrestricted: `When checked, pages within the Depth limit are crawled across the whole
  domain, not just paths under the seed URL.`

(Authentication, Sync Schedule 등 나머지 필드는 기존과 동일, 변경 없음.)

## 비범위

- 백엔드 `unrestricted` 필드 구현/검증 로직 — US-37에서 처리.
- `include_patterns`, `request_delay_ms` 등 기존에도 UI 미노출 상태인 다른 필드를 함께
  노출하는 작업 — 별도 스코프로 남김.

## 완료 기준

- [x] Web 커넥터 Create 모달에 "Include seed page as a document", "Unrestricted" 체크박스
      2개가 표시됨. `ConfigFields`가 Create/Edit 공유이므로 Edit에서 확인된 렌더링과 동일.
- [x] Web 커넥터 Edit 모달에서도 동일하게 표시되고, 기존 커넥터의 저장된 값(없으면 기본값)이
      올바르게 반영됨 — 사용자가 실행 중인 환경(나무위키 커넥터 Edit 모달)에서 체크박스
      2개와 ⓘ 아이콘이 정상 렌더링되는 스크린샷으로 확인 (2026-07-13).
- [x] 체크박스에 마우스를 올리면 툴팁 문구가 표시됨 — Radix `Tooltip`/`TooltipTrigger` 조합은
      Sidebar.tsx의 기존 사용 패턴을 그대로 재사용, `TooltipProvider`로 감쌈. 아이콘 렌더링은
      스크린샷으로 확인.
- [x] 저장 시 `POST /api/connectors` 또는 `PATCH /api/connectors/{id}` 요청 body에
      `skip_seed_pages`, `unrestricted`가 체크 상태에 맞게 포함됨 — `buildConfig()`에서
      `skip_seed_pages: raw.skip_seed_pages !== "false"`, `unrestricted: raw.unrestricted ===
      "true"`로 명시 매핑, `npm run typecheck`/`eslint` 통과. 사용자 확인 하에 완료 처리
      (별도 네트워크 탭 캡처는 생략).

## 의존성

- US-37 — 백엔드에 `unrestricted` config 필드가 있어야 이 UI로 저장한 값이 실제로 동작함.
  UI 자체는 US-37 완료 전에도 구현 가능하지만, 완료 기준의 엔드투엔드 확인은 US-37 완료 후에만
  가능.
