# RAG API — Claude Code 가이드

## 프로젝트 개요

Dagster + FastAPI 기반의 문서 인제스트 및 하이브리드 검색 파이프라인.
S3 호환 스토리지(MinIO) → Dagster 파이프라인(파싱·청킹·임베딩) → Qdrant(벡터 DB)
Redis는 ingest/delete 이벤트 큐로, Postgres는 KB/문서 메타데이터 저장소로 사용.

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| CLI | Typer (`rag-api` 스크립트) |
| API | FastAPI 0.111 + Uvicorn |
| 파이프라인 | Dagster 1.7 + LlamaIndex |
| 임베딩 | LlamaIndex (Ollama / OpenAI) + FastEmbed (BM25 sparse) |
| 벡터 DB | Qdrant (hybrid: dense + sparse) |
| 문서 스토리지 | MinIO (S3 호환) |
| 이벤트 큐 | Redis (ingest/delete) |
| 메타데이터 DB | PostgreSQL |
| 리랭킹 | Jina API (fallback: RRF 점수) |
| 설정 | Pydantic Settings + settings.yaml |

## Dev Setup Notes

커맨드는 `Makefile` 참조 (install, sync, lock, test, compile, docker-build, docker-push, clean 타겟).

- 패키지 매니저는 **uv** — `make install`(`uv sync --extra dev`)로 `rag_api`가 editable install됨 (import 경로 상세는 `.claude/skills/import-paths/SKILL.md`)
- CLI는 `rag-api` 콘솔 스크립트로 실행 (`rag-api serve`, `rag-api ingest --kb-id ... --key ...`)

## 하드 룰 (절대 하지 말 것)

- 이모지 사용 금지 — 코드, 로그, 문서 어디서도 이모지 불가. `logger.*()` 메시지와
  `print()` CLI 출력 모두 영어로 작성.
- 커밋 메시지에 `Co-Authored-By: Claude` 트레일러 금지 (2026-07-14 이후 신규 커밋)

## Session Start

세션 시작 시 아래 파일을 순서대로 읽는다:
1. `.claude/memory/MEMORY.md` — 과거 세션 학습 내용 인덱스
2. `.claude/specs/index.md`의 "진행 중" 표 (+ "마지막 채번 번호" 필드)

"진행 중" 표에 없는, 완료된 항목(History)이나 개별 spec 폴더(`specs/US-NN-*/`의
`spec.md`/`plan.md`/`task.md`)는 해당 항목을 실제로 조사·작업할 때만 연다. MEMORY.md
인덱스가 가리키는 개별 상세 파일도 이번 작업과 직접 관련될 때만 연다.

`.claude/skills/`는 세션 시작 시 미리 훑지 않는다 — analyst/designer/implementer/validator
각 서브에이전트가 자기 frontmatter의 `skills:` 목록에 따라 필요할 때 알아서 로드한다.
새 spec 작업 진행 순서(analyst → designer → implementer → validator)는 `.claude/commands/`의
`spec-new`/`spec-design`/`spec-implement`/`spec-validate`가 각각 처리한다 — 상태 갱신·번호
채번 같은 기계적 작업은 이 커맨드들 안에 이미 정의돼 있어 별도 규칙 문서를 세션 시작 시
읽을 필요가 없다.

## Memory (`.claude/memory/`)

전역 auto-memory 대신 이 로컬 저장소가 우선한다. `.claude/memory/`에 파일 작성 +
`MEMORY.md`에 한 줄 인덱스 (15개 초과 시 오래된 항목부터 `archive.md`로, 최근 5~10개만 유지).

**기록 대상**: 설계-구현 불일치 / 재발 가능한 함정 / 재구성 불가능한 피드백·결정 이유
(진행상황은 `specs/index.md`·각 spec 폴더가 다루므로 제외). 작고 정확하게 — 원본이
있으면 복제 대신 링크.

**기록 금지** (각각의 원본을 대신 본다): 코드에서 바로 파생되는 내용, `.claude/skills/`에
이미 있는 컨벤션, 해결된 버그의 수정 레시피(재발 방지 교훈만 한 문단으로 압축은 허용),
`docs/internal/known-issues.md`에 이미 있는 이슈.

**재검토** (해결/반영됐으면 삭제, 바뀌었으면 갱신): 작업 마무리 시 이번 대화에서 쓴 항목,
spec `done`(`/spec-validate`) 전환 시 관련 항목.
