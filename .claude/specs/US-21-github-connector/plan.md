# Plan 21 — GitHubConnector implementation (R-11)

## Covers

US-21

## Changes

1. `src/pipeline/ops/parse.py` — CODE_EXTENSIONS, CODE_LANGUAGE_MAP 상수 추가, FlatReader 매핑
2. `src/pipeline/ops/chunk.py` — CodeSplitter 자동 라우팅 (doc_type 기반)
3. `src/config/settings.py` — code_chunk_lines, code_chunk_lines_overlap 설정 추가
4. `settings.yaml` — 동일 기본값 추가
5. `src/connectors/github.py` — GitHubConnector 신규 구현
6. `requirements.txt` — tree-sitter, tree-sitter-languages 추가
7. `tests/unit/test_github_connector.py` — 단위 테스트

## Status

in-progress
