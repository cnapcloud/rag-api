# Tech Stack

## 전체 아키텍처

```
MinIO PUT 이벤트
  → Dagster Sensor
    → ingest_job (6단계 파이프라인)
      → Qdrant 저장
API 검색 요청
  → hybrid search (dense + sparse)
  → RRF merge (multi-KB)
  → Jina rerank
```

## 레이어별 기술

| 레이어 | 기술 | 버전 |
|--------|------|------|
| CLI | Typer | 0.12 |
| API | FastAPI + Uvicorn | 0.111 |
| 파이프라인 | Dagster | 1.7 |
| 문서 파싱/청킹 | LlamaIndex Core | 0.10+ |
| 임베딩 (dense) | LlamaIndex Ollama / OpenAI | — |
| 임베딩 (sparse) | FastEmbed (BM25) | 0.3+ |
| 벡터 DB | Qdrant | 1.9+ |
| 문서 스토리지 | MinIO (S3 호환) | 7.2+ |
| 메타데이터/캐시 | Redis | 5.0+ |
| 리랭킹 | Jina API (httpx) | — |
| 설정 | Pydantic Settings + PyYAML | 2.2 |
| 테스트 | pytest + pytest-asyncio | 8.0 |
| 린팅 | ruff | 0.4+ |
| 타입 체크 | mypy | 1.9+ |

## 실행 환경

- Python 3.11+
- `PYTHONPATH=src` 필수 (모든 import는 src/ 기준)
- 런타임 설정: `settings.yaml` → `get_settings()` 싱글턴

## 인프라 서비스 (docker-compose 기준)

| 서비스 | 기본 엔드포인트 |
|--------|----------------|
| MinIO | http://minio:9000 |
| Redis | redis:6379 |
| Qdrant | qdrant:6333 |
| Ollama | http://ollama:11434 |

## 핵심 설계 결정

- **Op = 순수 함수**: Dagster와 `runner.py` 양쪽에서 재사용 가능
- **ETag 중복 방지**: 동일 파일 재처리 방지 (Redis 캐시)
- **하이브리드 검색**: Dense(의미) + Sparse(키워드) 결합, alpha=0.5
- **RRF merge**: 여러 KB 결과를 Reciprocal Rank Fusion으로 통합
- **asyncio.gather**: Dense + Sparse 임베딩 병렬 실행
- **Fallback**: Jina reranker 실패 시 RRF 점수 사용
