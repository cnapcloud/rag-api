---
name: feedback-conventions
description: 이 프로젝트에서 지켜야 할 코딩 컨벤션 및 테스트 패턴
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 8d64a12e-8ccb-46d4-9977-4b334c0ec4a7
---

**import는 `rag_api.` 최상위 패키지 기준**: `from rag_api.config.settings import get_settings` (O), `from config.settings import get_settings` / `from src.config.settings` (X). `rag_api`가 editable install되어 있어 `src/rag_api/`가 `rag_api` 패키지로 바로 임포트되기 때문 (PYTHONPATH 설정 불필요).

**Why:** pyproject.toml의 hatchling 설정(`"src" = ""`)으로 `uv sync`가 `rag_api`를 editable install함. `src/rag_api/` 하나의 패키지로 통합되어 있어 접두사 없는 import는 더 이상 존재하지 않는 모듈을 가리킴.

**How to apply:** 새 파일 작성 시 기존 파일의 import 패턴 참고. `from src.` 형태나 `rag_api.` 접두사가 빠진 형태가 보이면 버그.

---

**SentenceSplitter 테스트 텍스트 주의**: `"A" * N`처럼 공백 없는 연속 문자는 단일 청크로 반환됨. 반드시 `"word " * N` 또는 실제 문장 사용.

**Why:** SentenceSplitter는 문장/단어 경계로 분할하므로 공백이 없으면 분할 불가.

**How to apply:** chunk Op 테스트 작성 시 `"sample text " * N` + 작은 chunk_size 조합 사용.

---

**인프라는 conftest.py 픽스처로**: 테스트에서 실제 Redis/Qdrant/MinIO/Postgres 연결 생성 금지. `mock_redis`, `mock_qdrant`, `mock_minio`, `mock_postgres` 픽스처 사용.

**Why:** CI 환경에 인프라가 없음. 단위 테스트는 외부 의존성 없이 실행되어야 함.
