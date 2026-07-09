---
paths:
  - "tests/**/*.py"
---

# 테스트 패턴

- 외부 인프라(Redis, Qdrant, MinIO, Postgres)는 항상 Mock 사용
- `tests/conftest.py` 픽스처(`mock_redis`, `mock_qdrant`, `mock_minio`, `mock_postgres`)를 우선 사용
- 실제 Redis/Qdrant/MinIO/Postgres 연결을 테스트에서 생성 금지

## 실행 명령어

```bash
.venv/bin/python -m pytest tests/unit/ -v
.venv/bin/python -m pytest tests/ -v
```
