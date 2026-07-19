---
name: config_settings_pipeline_circular_import_pitfall
description: config/settings.py importing a type from pipeline/steps/*.py at module level risks circular import — those step modules already import settings.py at module level for resolve_settings/get_settings
metadata:
  type: project
---

`config/settings.py`가 `pipeline/steps/` 아래 모듈의 타입(예: `chunk.py`의
`ChunkStrategy = Literal["recursive", "semantic"]`)을 재사용하려고 모듈 레벨에서 import하면,
그 step 모듈이 이미 `from rag_api.config.settings import resolve_settings`(또는 `get_settings`)를
모듈 레벨에서 하고 있어 순환 임포트가 난다 — `pipeline/steps/*.py`는 거의 전부 `resolve_settings`를
쓴다.

**Why**: US-45(KB 설정 필드 스키마)에서 `chunking.strategy: str`을 `chunk.py`의 `ChunkStrategy`로
승격하려다 발견. `config/settings.py`가 `Settings`(다른 모든 모듈이 의존하는 최하위 계층)인데
반대로 상위 계층인 `pipeline/steps/`를 import하면 방향이 뒤집힌다.

**How to apply**: 이런 상황이 다시 생기면(예: `dedup/` 쪽 타입을 `settings.py`가 재사용하려는
경우) `pipeline/steps/*.py` 쪽의 `resolve_settings`/`get_settings` import를 함수 내부 지연
import로 옮겨서 방향을 끊는다(호출 시점엔 `config/settings.py`가 이미 완전히 로드돼 있으므로
안전) — 반대로 `config/settings.py` 쪽을 지연 import로 하면 `Literal` 타입 자체가 클래스 필드
어노테이션에 즉시 필요해서 안 먹힌다. `chunk.py`의 `resolve_settings` import가 실제로 이렇게
옮겨졌다 — 사용처가 `chunk()` 함수 1곳뿐이라 영향이 작았음.
