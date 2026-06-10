---
name: project-architecture
description: "RAG API 프로젝트 전체 아키텍처 — 기술 스택, 파이프라인 흐름, 핵심 파일 위치"
metadata: 
  node_type: memory
  type: project
  originSessionId: 8d64a12e-8ccb-46d4-9977-4b334c0ec4a7
---

Dagster + FastAPI 기반 문서 인제스트 및 하이브리드 검색 RAG 파이프라인.

**흐름**: MinIO PUT → Dagster Sensor → ingest_job (validate → parse → chunk → embed → upsert → meta)

**기술 스택**: FastAPI(API), Dagster(파이프라인), LlamaIndex(파싱/청킹/임베딩), Qdrant(벡터 DB), MinIO(문서 저장), Redis(ETag 캐시 + 메타데이터), FastEmbed(BM25 sparse), Jina(리랭킹)

**핵심 경로**:
- 파이프라인 Op: `src/pipeline/ops/` (validate → parse → chunk → embed → upsert → meta)
- Dagster 래퍼: `src/dagster_pipeline/`
- 인프라 클라이언트: `src/infra/` (minio.py, redis.py, qdrant.py)
- API 라우터: `src/api/routers/`
- 설정 싱글턴: `src/config/settings.py` (`get_settings()`)
- 런타임 설정: `settings.yaml`

**Why:** PYTHONPATH=src 기준이므로 모든 import는 `from config.settings`처럼 src/ 접두사 없이.

**How to apply:** 새 Op/라우터 작성 시 기존 Op 함수 시그니처 패턴 따를 것. Dagster 없이도 `runner.py`로 직접 테스트 가능.
