---
name: import-paths
description: rag_api 모듈 import 경로 규칙 (from src. 금지). implementer가 새 파일을 만들거나 import 문을 쓸 때 사용.
---

# Import 경로 규칙

`rag_api`는 editable install되어 있으므로(`make install` = `uv sync --extra dev`)
`PYTHONPATH` 설정 없이 `src/rag_api/`가 `rag_api` 최상위 패키지로 바로 임포트된다.

```python
# 금지
from src.config.settings import get_settings

# 올바름
from rag_api.config.settings import get_settings
```

`src.`로 시작하는 import는 어디에도(코드/테스트) 쓰지 않는다.

## 잘못된 패턴 검색

작업 마무리 전에 이번에 건드린 파일에 새로 들어간 게 없는지 확인한다.

```bash
grep -r "from src\." src/ tests/
```
