# Progress Tracking

## Index Files

| File | Purpose |
|------|---------|
| `.claude/backlogs/backlog.md` | All user stories — ID, title, status |
| `.claude/plans/plan.md` | All implementation plans — plan number, title, covered US, status |

## Reference Documents

Before creating a new backlog item or implementation plan, read the following documents to ensure consistency with the existing architecture and data model:

| File | Purpose |
|------|---------|
| `docs/internal/architecture.md` | System architecture — component layout, data flow, technology choices |
| `docs/internal/design/data-schema.md` | Data schema — Qdrant PointStruct payload, Postgres/Redis fields |

These documents describe the current state of the system. Backlog items and plans must not propose changes that contradict or duplicate what is already documented here. If a new feature changes the schema, update these documents as part of the implementation.

## When to Read

Read both index files at the **start of any session** that involves implementing a feature, fixing a bug, or planning new work. This gives an immediate picture of what is done and what is pending without opening individual detail files.

## Status Values

| Value | Meaning |
|-------|---------|
| `todo` | Not started |
| `in-progress` | Being implemented in current or recent session |
| `done` | Implemented and tested |
| `blocked` | Cannot proceed — dependency or decision needed |

## When to Update

- Change status to `in-progress` when work on an item begins.
- Change status to `done` when implementation is complete and tests pass.
- Add a new row whenever a new backlog item (US-XX) or plan file is created.
- Never leave status stale — if the row says `todo` but work is done, fix the row before ending the session.

## Backlog File Location

Backlog detail files are organized by status:

| Location | When |
|----------|------|
| `.claude/backlogs/todo/US-XX-*.md` | Status is `todo`, `in-progress`, or `blocked` |
| `.claude/backlogs/US-XX-*.md` | Status is `done` |

When marking an item `done`:
1. Move the detail file from `backlogs/todo/` to `backlogs/`.
2. Update the link in `backlog.md` (remove the `todo/` prefix).

## Plan File Naming

Plan numbers MUST match the backlog US number they implement:
- US-08 → `08-<slug>.md` (not `06-`, not a sequential counter)
- If a plan covers multiple US items, use the primary US number.
- The slug MUST match the backlog file's slug exactly (e.g. `US-08-min-score-filter.md` →
  `08-min-score-filter.md`, not a reworded title).
- Exception: if the backlog file already contains sufficient implementation detail that a
  separate plan would be redundant, skip the plan file and mark it `통합(backlog 참고)` in
  `plans/plan.md` instead of leaving the row missing.

After creating a plan file, always add a row to `plans/plan.md` in the same session.
Skipping this step is a common omission — treat it as mandatory, not optional.

## Traceability

See `.claude/rules/conventions/07-traceability.md` for how prd.md, design docs, backlog,
and plan files must link to each other (fixed-position links + filename keyword alignment).
