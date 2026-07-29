---
name: local-postgres-masks-missing-test-mocks
description: This dev machine has a real reachable Postgres on localhost:5432 — unit tests that forget to mock infra.postgres calls pass locally but would hang/fail in CI
metadata:
  type: project
---

This workstation has a real Postgres reachable at `settings.yaml`'s default
(`localhost:5432`), so any test that exercises a code path calling `infra/postgres.py`
functions without mocking them does NOT fail loudly here — it silently makes a real DB
round-trip (e.g. `get_kb_settings_overrides(kb_id)` on a nonexistent `kb_id` just returns `{}`)
and the test passes anyway, hiding a hard-rule violation
(`.claude/rules/00-hard-rules.md` §3: no real infra in tests).

**Why this bit US-03**: `rag/retriever.py::_search_kb` started calling `resolve_settings(kb_id)`
unconditionally (needed for KB-scoped `retrieval.auto_merge` overrides). Every existing
`test_search.py` test that passed a real-looking `kb_id` kept passing locally with zero mocks
for `get_kb_settings_overrides` — only `.venv/bin/python -c "..."` manually calling that
function directly, or running in an environment without local Postgres, revealed it.

**How to apply**: Whenever a new code path starts calling `resolve_settings(kb_id)` (or any
other `infra/postgres.py` function) with a non-None `kb_id`, grep existing tests exercising that
path and confirm `rag_api.infra.postgres.get_kb_settings_overrides` (or whichever function) is
explicitly mocked — a green local run is not sufficient evidence here.
