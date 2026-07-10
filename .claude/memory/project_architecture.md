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

**기술 스택**: FastAPI(API), Dagster(파이프라인), LlamaIndex(파싱/청킹/임베딩), Qdrant(벡터 DB), MinIO(문서 저장), Redis(ingest/delete 큐), PostgreSQL(KB/문서 메타데이터), FastEmbed(BM25 sparse), Jina(리랭킹)

**핵심 경로**:
- 파이프라인 Op: `src/rag_api/pipeline/ops/` (validate → parse → chunk → embed → upsert → meta)
- Dagster 래퍼: `src/rag_api/defs/`
- 인프라 클라이언트: `src/rag_api/infra/` (s3.py=스토리지, redis.py=큐, postgres.py=메타데이터, qdrant.py=벡터, crypto.py, dagster_utils.py)
- API 라우터: `src/rag_api/api/routers/`
- 설정 싱글턴: `src/rag_api/config/settings.py` (`get_settings()`)
- 런타임 설정: `settings.yaml`

**Why:** `rag_api`는 editable install되어 있어 `PYTHONPATH` 설정 없이 `src/rag_api/`가 `rag_api` 최상위 패키지로 바로 임포트됨(2026-07-09 확인, 이전엔 PYTHONPATH=src가 필요했으나 uv 기반 editable install 전환 이후 불필요). 모든 import는 `from rag_api.config.settings`처럼 `rag_api.` 접두사를 붙임. US-11에서 KB/문서 메타데이터가 Redis→Postgres로 이전되며 Redis는 ingest/delete 큐 전용이 됨, infra 파일도 `minio.py`→`s3.py`로 이름이 바뀜.

**How to apply:** 새 Op/라우터 작성 시 기존 Op 함수 시그니처 패턴 따를 것. Dagster 없이도 `runner.py`로 직접 테스트 가능.
