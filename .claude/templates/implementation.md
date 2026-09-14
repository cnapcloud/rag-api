# US-NN: <제목> — 구현 기록

> 담당: `implementer` · spec 워크플로우 3단계 실행 · 템플릿: `.claude/templates/implementation.md`

**대상**: [design.md](design.md) / [task.md](task.md)

## Task 현황

| ID | 상태 |
|---|---|
| T1 | <todo/in-progress/done/blocked> |

## 진행 기록

```
- **[<Task ID>] done** — AC: <F1-1, F1-2> — 테스트: `<pytest 명령>` — <n> passed
- **[<Task ID>] blocked** — AC: <AC> — 유형: [구현/설계] — <design.md/task.md 대비 무엇이
  어긋났는지, 무엇을 고쳐야 다음 시도가 가능한지 구체적으로>
```

신규 패키지를 설치한 task는 `done` 블록에 `uv add`로 실제 설치된 패키지명 + 버전(예:
`신규 패키지: <pkg>==<실제 설치 버전>`)을 덧붙인다.

## 외부 이상 징후

<없으면 "(없음)">

```
- `<make test|lint|typecheck>` — `<파일:줄 또는 테스트 노드 ID>` — <실제 에러/실패 내용>
```
