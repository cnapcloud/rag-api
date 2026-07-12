# Progress Tracking

목적: `.claude/backlogs/backlog.md` / `.claude/plans/plan.md` 인덱스로 현재 진행 상황을 파악하고
최신 상태로 유지하기 위한 규칙. 세션마다 참고하는 짧은 북키핑 규칙만 담는다 — 문서 간 링크
포맷 등 실제로 backlog/design 문서를 작성할 때만 필요한 상세 규칙은
`07-traceability.md`에 있다.

## 1. Index Files

| File | Purpose |
|------|---------|
| `.claude/backlogs/backlog.md` | All user stories — ID, title, status |
| `.claude/plans/plan.md` | All implementation plans — plan number, title, covered US, status |

## 2. Reference Documents

Before creating a new backlog item or implementation plan, read the following documents to ensure consistency with the existing architecture and data model:

| File | Purpose |
|------|---------|
| `docs/internal/architecture/README.md` | System architecture index — see also `application.md`, `technical.md`, `runtime.md` in the same folder |
| `docs/internal/design/data-schema.md` | Data schema — Qdrant PointStruct payload, Postgres/Redis fields |

These documents describe the current state of the system. Backlog items and plans must not propose changes that contradict or duplicate what is already documented here. If a new feature changes the schema, update these documents as part of the implementation.

## 3. When to Read

Read both index files at the **start of any session** that involves implementing a feature, fixing a bug, or planning new work. This gives an immediate picture of what is done and what is pending without opening individual detail files.

## 4. Status Values

| Value | Meaning |
|-------|---------|
| `todo` | Not started |
| `in-progress` | Being implemented in current or recent session |
| `done` | Implemented and tested |
| `blocked` | Cannot proceed — dependency or decision needed |

## 5. When to Update

- Change status to `in-progress` when work on an item begins.
- Change status to `done` when implementation is complete and tests pass. Before doing so, run
  the done-transition checklist in `07-traceability.md` — it applies even when there is no
  separate plan file (`통합(backlog 참고)` case).
- Add a new row whenever a new backlog item (US-XX) or plan file is created. New backlog items
  MUST use `.claude/backlogs/_TEMPLATE.md` — creating one in the old ad-hoc format is not
  allowed. Plan file naming rules are in `07-traceability.md`.
- Never leave status stale — if the row says `todo` but work is done, fix the row before ending the session.

## 6. Backlog File Location

Backlog detail files are organized by status:

| Location | When |
|----------|------|
| `.claude/backlogs/todo/US-XX-*.md` | Status is `todo`, `in-progress`, or `blocked` |
| `.claude/backlogs/US-XX-*.md` | Status is `done` |

When marking an item `done`:
1. Move the detail file from `backlogs/todo/` to `backlogs/`.
2. Update the link in `backlog.md` (remove the `todo/` prefix).
