# RAG API — Claude Code 가이드

## 프로젝트 개요

Dagster + FastAPI 기반의 문서 인제스트 및 하이브리드 검색 파이프라인.
MinIO(문서 스토리지) → Dagster 파이프라인(파싱·청킹·임베딩) → Qdrant(벡터 DB)
Redis는 ETag 중복 방지 캐시 + KB/문서 메타데이터 저장소로 사용.

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| CLI | Typer (`rag-api` 스크립트) |
| API | FastAPI 0.111 + Uvicorn |
| 파이프라인 | Dagster 1.7 + LlamaIndex |
| 임베딩 | LlamaIndex (Ollama / OpenAI) + FastEmbed (BM25 sparse) |
| 벡터 DB | Qdrant (hybrid: dense + sparse) |
| 문서 스토리지 | MinIO (S3 호환) |
| 메타데이터 캐시 | Redis |
| 리랭킹 | Jina API (fallback: RRF 점수) |
| 설정 | Pydantic Settings + settings.yaml |

## 디렉토리 구조

```
src/
  main.py                    # Typer CLI 진입점
  config/settings.py         # Settings 싱글턴 (get_settings())
  api/
    app.py                   # FastAPI 팩토리
    routers/                 # health, kb, docs, search
  pipeline/ops/              # 순수 함수 파이프라인 Op
    validate.py  → parse.py → chunk.py → embed.py → upsert.py → meta.py
  pipeline/ops/runner.py     # CLI/테스트용 직접 실행 래퍼
  defs/          # Dagster @op 래퍼 + sensor + resource
  rag/                       # retriever, merger(RRF), reranker
  infra/
    minio.py   # MinIO 클라이언트 + 이벤트 폴링
    redis.py   # ETag 캐시 + KB/문서 메타데이터 CRUD
    qdrant.py  # Qdrant 클라이언트 + 컬렉션 관리
tests/
  conftest.py         # FakeRedis, mock_qdrant, mock_minio 픽스처
  unit/               # test_chunk, test_embed, test_search, test_validate
  integration/        # test_ingest_pipeline, test_search_api
  dagster/            # test_sensor
```

## 개발 명령어

```bash
# 환경 설정
python3 -m venv .venv && pip install -r requirements.txt

# 테스트 (PYTHONPATH 필수)
PYTHONPATH=src .venv/bin/python -m pytest tests/unit/ -v
PYTHONPATH=src .venv/bin/python -m pytest tests/ -v

# Makefile 단축키
make test          # venv 생성 + 전체 테스트
make docker-build  # 이미지 빌드
make docker-run    # 컨테이너 실행 (포트 8000)
make clean         # venv + build 산출물 삭제

# 린팅 / 타입 체크
.venv/bin/ruff check src/ tests/
.venv/bin/mypy src/

# CLI 직접 실행
PYTHONPATH=src .venv/bin/python -m main serve
PYTHONPATH=src .venv/bin/python -m main ingest --kb-id kb-test --key doc.pdf
```

## 파이프라인 흐름

```
MinIO PUT 이벤트
  → Dagster Sensor (minio_sensor / upload_sensor)
    → ingest_job
      1. validate_op   — ETag 중복 체크, 파일 크기 제한
      2. parse_op      — MinIO 다운로드 → LlamaIndex Document[]
      3. chunk_op      — NodeParser (document_aware / recursive / semantic)
      4. embed_op      — Dense + Sparse 임베딩 (asyncio.gather 병렬)
      5. upsert_op     — 기존 청크 삭제 후 Qdrant 업서트
      6. meta_op       — Redis 상태(indexed) + 메타데이터 갱신
```

각 Op은 `src/pipeline/ops/` 의 순수 함수이며, `runner.py`로 Dagster 없이도 실행 가능.

## API 엔드포인트 요약

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /health | 상태 확인 |
| GET | /ready | 인프라 헬스체크 (Qdrant/Redis/MinIO/Ollama) |
| GET/POST/DELETE | /api/kb | KB CRUD |
| POST | /api/kb/{id}/docs/upload | 단일 파일 업로드 |
| POST | /api/kb/{id}/docs/upload/batch | 배치 업로드 |
| GET | /api/kb/{id}/docs | 문서 목록 |
| DELETE | /api/kb/{id}/docs/{key} | 문서 삭제 |
| POST | /api/search | 하이브리드 검색 (multi-KB RRF) |

## 코드 컨벤션

- **import 경로**: `from config.settings import get_settings` (절대경로, `src/` 접두사 없음)
  - `PYTHONPATH=src`로 실행하기 때문. `from src.config...` 형태는 잘못된 것.
- **타입 힌트**: 모든 함수에 필수. Pydantic 모델 우선 사용.
- **라인 길이**: 100자 (ruff 설정)
- **포맷터**: ruff (E, F, I, UP 규칙)
- **테스트 스타일**: 외부 인프라는 conftest.py 픽스처로 Mock. 실제 Redis/Qdrant 연결 금지.
- **로거**: 모듈별 `logger = logging.getLogger(__name__)` 사용.

## 설정 구조 (settings.yaml)

런타임 설정은 `settings.yaml` → `get_settings()` 싱글턴으로 접근.
환경변수로 오버라이드 가능 (Pydantic Settings). 코드에 하드코딩 금지.

주요 설정 키: `minio`, `redis`, `qdrant`, `dagster`, `ingestion`, `chunking`, `embedding`, `retrieval`, `knowledge_bases`

## 알려진 이슈 / 주의사항

현재 미해결 이슈 없음.

## 하드 룰 (절대 하지 말 것)

- `get_settings()`를 우회하여 설정값 하드코딩 금지
- `from src.config...` 형태의 import 금지 (PYTHONPATH=src 기준)
- 인프라 클라이언트를 테스트에서 실제 연결로 사용 금지 (항상 conftest.py 픽스처 사용)
- `infra/minio.py`와 `infra/redis.py`를 혼동하지 말 것 (파일명과 내용이 불일치했던 버그 전례 있음)
- 파이프라인 Op 함수는 부작용 없는 순수 함수로 유지 (Dagster와 runner.py 양쪽에서 재사용)
- 이모지 사용 금지 — 코드, 로그, 문서 어디서도 이모지 불가
- `logger.*()` 메시지와 `print()` CLI 출력 모두 영어로 작성
