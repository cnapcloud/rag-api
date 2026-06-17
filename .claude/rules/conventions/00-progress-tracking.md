# Progress Tracking

## Index Files

| File | Purpose |
|------|---------|
| `.claude/backlogs/backlog.md` | All user stories — ID, title, status |
| `.claude/plans/plan.md` | All implementation plans — plan number, title, covered US, status |

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

## Plan File Naming

Plan numbers MUST match the backlog US number they implement:
- US-08 → `08-<slug>.md` (not `06-`, not a sequential counter)
- If a plan covers multiple US items, use the primary US number.

After creating a plan file, always add a row to `plans/plan.md` in the same session.
Skipping this step is a common omission — treat it as mandatory, not optional.
