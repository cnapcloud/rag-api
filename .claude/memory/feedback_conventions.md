---
name: feedback-conventions
description: 이 프로젝트에서 지켜야 할 코딩 컨벤션 및 테스트 패턴
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 8d64a12e-8ccb-46d4-9977-4b334c0ec4a7
---

**import는 src/ 접두사 없이**: `from config.settings import get_settings` (O), `from src.config.settings` (X). PYTHONPATH=src 기준으로 실행하기 때문.

**Why:** pyproject.toml의 hatchling 설정과 Makefile의 PYTHONPATH=src 조합으로 동작.

**How to apply:** 새 파일 작성 시 기존 파일의 import 패턴 참고. `from src.` 형태가 보이면 버그.

---

**SentenceSplitter 테스트 텍스트 주의**: `"A" * N`처럼 공백 없는 연속 문자는 단일 청크로 반환됨. 반드시 `"word " * N` 또는 실제 문장 사용.

**Why:** SentenceSplitter는 문장/단어 경계로 분할하므로 공백이 없으면 분할 불가.

**How to apply:** chunk Op 테스트 작성 시 `"sample text " * N` + 작은 chunk_size 조합 사용.

---

**인프라는 conftest.py 픽스처로**: 테스트에서 실제 Redis/Qdrant/MinIO 연결 생성 금지. `mock_redis`, `mock_qdrant`, `mock_minio` 픽스처 사용.

**Why:** CI 환경에 인프라가 없음. 단위 테스트는 외부 의존성 없이 실행되어야 함.
