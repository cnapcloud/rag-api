---
id: US-17
title: parse_op HTML clean reader — strip nav/footer/script (R-08)
status: done
requirement: docs/dev/requirement-multi-source-ingest.md — R-08
---

## User Story

As an operator ingesting HTML documents,
I want nav, footer, header, script, and style content stripped before indexing,
so that search results are not polluted by boilerplate navigation text.

## Background

R-08 specifies: HTML (doc_type=html, LlamaIndex HTML reader, strip nav/footer/script).
The existing `HTMLTagReader` only extracts `<section>` tags by default and has no
mechanism to remove unwanted structural tags (nav, footer, header, script, style).
RST plain-text fallback via `FlatReader` is already implemented.

## Scope

- Implement `HTMLCleanReader` in `src/pipeline/ops/parse.py`:
  - Uses BeautifulSoup (already installed as a transitive dependency)
  - Removes tags: nav, footer, header, script, style, aside
  - Extracts text from `<body>` (or full document if no body tag)
  - Returns a single `Document` per file
- Replace `HTMLTagReader` with `HTMLCleanReader` in `_get_file_extractor()`
- Add unit tests in `tests/unit/test_parse_html.py`

## Out of Scope

- RST: already covered by `FlatReader` fallback (R-08 plain-text fallback accepted)
- WebConnector (R-09), ConfluenceConnector (R-10), GitHubConnector (R-11)

## Acceptance Criteria

- [ ] `HTMLCleanReader.load_data()` removes nav, footer, header, script, style, aside content
- [ ] Body text is preserved
- [ ] Returns a single `Document` per HTML file
- [ ] `doc_type=html` is set correctly (via existing `suffix.lstrip(".")` logic)
- [ ] `.html` and `.htm` both use `HTMLCleanReader`
- [ ] Unit tests pass with mock HTML containing nav/footer/script/body content
