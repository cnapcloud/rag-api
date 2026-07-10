---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Import 경로 규칙

`rag_api`는 editable install되어 있으므로 `PYTHONPATH` 설정 없이 `src/rag_api/`가 `rag_api` 최상위 패키지로 바로 임포트된다.

```python
# 금지
from src.config.settings import get_settings

# 올바름
from rag_api.config.settings import get_settings
```

## 잘못된 패턴 검색

```bash
grep -r "from src\." src/
```
