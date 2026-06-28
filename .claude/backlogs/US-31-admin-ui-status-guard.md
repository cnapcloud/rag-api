# US-31 — Admin UI Status Guard

## 요약

rag-admin에서 bulk reindex / delete 클릭 시 활성 상태 doc을 proactive 체크하고,
mutation error handler에서 409 응답을 감지해 적절한 토스트를 표시한다.

## 배경

US-30(API Status Guard)으로 백엔드 차단이 구현됐으나, UI 레이어 가드는 미구현 상태.
설계 문서: `docs/internal/design/doc-status-guard.md` §7

## 구현 항목

- SG-06: `docs/index.tsx` — bulk reindex / delete 클릭 시 선택 목록에 활성 상태 doc 포함 여부 proactive 체크 → 토스트
- SG-07: `docs/index.tsx`, `DocDetailPanel.tsx` — mutation error handler에서 409 감지 → 토스트

## 인수 조건

- 활성 상태 doc이 선택 목록에 포함된 상태로 Reindex Selected / Delete Selected 클릭 시:
  API 미호출, 토스트 "작업 중인 문서가 포함되어 있어 처리할 수 없습니다." 표시
- 409 응답 수신 시:
  토스트 "일부 문서가 처리 중이어서 작업이 실패했습니다." 표시 (reindex, delete 모두)
