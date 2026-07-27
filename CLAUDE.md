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

## 디렉토리 구조
구조는 `ls`/`view`로 확인 가능하므로 여기서는 **파일 배치 규칙**만 기록한다:

- `api/routers/` — health, kb, docs, search 라우터
- `pipeline/steps/` — 순수 함수 Step (validate → parse → chunk → embed → upsert → meta), `runner.py`로 Dagster 없이도 직접 실행 가능
- `pipeline/queue/`, `pipeline/utils/` — QueueWorker(Dagster 미사용 모드) 및 파이프라인 보조 유틸
- `defs/` — Dagster `@op` 래퍼 + `jobs/`, `ops/`, `resources/`, `schedules/`, `sensors/`
- `rag/` — retriever, merger(RRF), reranker
- `infra/` — 실제 인프라 접근은 이 디렉토리에만: `s3.py`(스토리지), `redis.py`(ingest/delete 큐), `postgres.py`(KB/문서 메타데이터), `qdrant.py`(벡터), `crypto.py`(커넥터 시크릿 암호화), `dagster_utils.py`(Dagster GraphQL 원격 제어)
- `connectors/` — 외부 소스 커넥터 (confluence, github, web)
- `mcp_server/` — MCP 서버
- `tracing/` — OTel 트레이싱

## Dev Setup Notes

커맨드는 `Makefile` 참조 (install, sync, lock, test, compile, docker-build, docker-push, clean 타겟).

- 패키지 매니저는 **uv** — `make install`(`uv sync --extra dev`)로 `rag_api`가 editable install되므로 `PYTHONPATH` 설정 없이 바로 임포트/테스트 가능
- CLI는 `rag-api` 콘솔 스크립트로 실행 (`rag-api serve`, `rag-api ingest --kb-id ... --key ...`) — `python -m main`은 존재하지 않는 모듈이므로 사용 금지

## 코드 컨벤션

- **타입 힌트**: 모든 함수에 필수. Pydantic 모델 우선 사용.
- **라인 길이**: 100자 (ruff 설정)
- **포맷터**: ruff (E, F, I, UP 규칙)
- **예외 처리**: `RAGError` 계층(`ConfigError`/`IngestValidationError`/`NotFoundError`/`ConflictError`) 사용, `from e` chaining 필수. (`.claude/rules/conventions/05-exception-handling.md`)
- **로거**: 모듈별 `logger = logging.getLogger(__name__)` 사용. (`.claude/rules/conventions/06-logging.md`)

## 하드 룰 (절대 하지 말 것)

전체 상세(코드 예시 포함)는 [`.claude/rules/00-hard-rules.md`](.claude/rules/00-hard-rules.md) 참조.

- `get_settings()`를 우회하여 설정값 하드코딩 금지
- `from src.config...` 형태의 import 금지 (`rag_api`는 editable install되어 있어 `PYTHONPATH` 불필요)
- 인프라 클라이언트를 테스트에서 실제 연결로 사용 금지 (항상 conftest.py 픽스처 사용, `.claude/rules/conventions/02-testing.md`)
- `infra/` 파일 역할 혼동 금지: `s3.py`(스토리지) / `redis.py`(큐) / `postgres.py`(메타데이터) / `qdrant.py`(벡터)
- `infra/` 파일 수정 전 반드시 Read/grep으로 내용 확인 (복붙 사고 전례, 2026-06-07)
- 파이프라인 Op 함수는 부작용 없는 순수 함수로 유지 (Dagster와 runner.py 양쪽에서 재사용)
- 이모지 사용 금지 — 코드, 로그, 문서 어디서도 이모지 불가
- `logger.*()` 메시지와 `print()` CLI 출력 모두 영어로 작성
- 커밋 메시지에 `Co-Authored-By: Claude` 트레일러 금지 (2026-07-14 이후 신규 커밋)

## Session Start

세션 시작 시 아래 파일을 순서대로 읽는다:
1. `.claude/memory/MEMORY.md` — 과거 세션 학습 내용 인덱스
2. `.claude/backlogs/backlog.md`의 Summary만
3. `.claude/plans/plan.md`의 Summary만

각 파일의 Full History/개별 상세 파일은 해당 항목을 실제로 조사·작업할 때만 연다.
MEMORY.md 인덱스가 가리키는 개별 상세 파일은 이번 작업과 직접 관련될 때만 연다.

위 3개 외 `.claude/rules/` 하위 파일(`README.md` 포함)은 세션 시작 시 사전 탐색하지
않는다. 해당 컨벤션이 실제로 필요한 작업(예: infra 파일 수정, git merge, backlog `done`
전환)을 할 때만 그때 연다.

backlog/plan 진행 상황 갱신 규칙은 `.claude/rules/conventions/00-progress-tracking.md`(세션
북키핑)에, design 문서·backlog 작성 시 링크 포맷은 `07-traceability.md`에 있다.

## Memory (`.claude/memory/`)

기록 대상: 설계-구현 불일치 / 재발 가능한 함정 / 재구성 불가능한 피드백·결정 이유
(진행상황은 backlog/plan에 있으므로 제외)

원칙: 작고 정확하게. 원본(코드/문서)이 있으면 복제 대신 링크로 참조한다.

**기록 금지** (아래 각각의 원본):
- 코드에서 바로 파생되는 내용 — 코드 자체
- `.claude/rules/`에 이미 있는 컨벤션 — 해당 rules 파일
- 해결된 버그의 수정 레시피 — 커밋 + 코드 (재발 방지 교훈만 한 문단으로 압축해 남기는 건 허용)
- `docs/internal/known-issues.md`에 이미 있는 이슈 — 그 문서

**재검토** (해결/반영됐으면 삭제, 바뀌었으면 갱신):
- 작업 마무리 응답 시 — 이번 대화에서 언급/사용한 항목
- backlog `done` 전환 시 — 관련 항목

`.claude/memory/`에 파일 작성 + `MEMORY.md`에 한 줄 인덱스 (전역 메모리 대신, 충돌 시 이쪽 우선)
인덱스 15개 초과 시 오래된 항목은 `archive.md`로 이동, 최근 5~10개만 유지
