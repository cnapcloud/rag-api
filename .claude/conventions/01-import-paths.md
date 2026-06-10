# Import 경로 규칙

## 핵심 규칙

`PYTHONPATH=src` 기준으로 실행하므로 **모든 import는 `src/` 접두사 없이** 작성.

```python
# 올바름
from config.settings import get_settings
from infra import redis as redis_infra
from pipeline.ops.chunk import chunk

# 잘못됨
from src.config.settings import get_settings
from src.infra import redis as redis_infra
```

## 왜 이렇게 하는가

`pyproject.toml`의 hatchling 설정이 `src/`를 패키지 루트로 지정.
`Makefile`과 `pytest.ini_options`도 `PYTHONPATH=src`를 기준으로 동작.

## 확인 방법

`infra/redis.py`가 과거에 `from src.config.settings import get_settings`로 잘못 작성된 전례가 있음.
새 파일 작성 시 기존 파일의 import 패턴을 반드시 참조할 것.

```bash
# 잘못된 import 패턴 검색
grep -r "from src\." src/
```

## 내부 모듈 import 순서 (ruff I 규칙)

```python
from __future__ import annotations  # 항상 첫 줄

import logging                       # 표준 라이브러리
from typing import Literal

from llama_index.core import Document  # 서드파티

from config.settings import get_settings  # 내부 모듈
from infra import redis as redis_infra
```
