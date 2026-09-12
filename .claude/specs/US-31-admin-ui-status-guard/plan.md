# Plan 31 — Admin UI Status Guard

Covers: US-31

## 변경 파일 (rag-admin)

| 파일 | 변경 내용 |
|------|-----------|
| `src/lib/utils.ts` | `isDocActive(status)` 헬퍼 추가 |
| `src/routes/docs/index.tsx` | SG-06 proactive check, SG-07 409 onError |
| `src/components/DocDetailPanel.tsx` | SG-07 409 onError |

## 구현 순서

1. `utils.ts` — stable set 여집합으로 `isDocActive` 정의
2. `docs/index.tsx` — Reindex Selected / Delete Selected 핸들러에 proactive 체크 추가 (SG-06); `reindexMut` / `deleteMut` onError에 409 감지 추가 (SG-07)
3. `DocDetailPanel.tsx` — `reindexMut` / `deleteMut` onError에 409 감지 추가 (SG-07)

## 토스트 메시지

| 케이스 | 메시지 |
|--------|--------|
| SG-06 proactive | "작업 중인 문서가 포함되어 있어 처리할 수 없습니다." |
| SG-07 reactive 409 | "일부 문서가 처리 중이어서 작업이 실패했습니다." |
