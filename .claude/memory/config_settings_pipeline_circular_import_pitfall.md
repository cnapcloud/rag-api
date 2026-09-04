---
name: config_settings_pipeline_circular_import_pitfall
description: config/settings.py must not import from pipeline/steps/chunk.py (or any llama_index-importing module) at module level — use the dependency-free chunk_types.py leaf; the edge both risks circular import and drags llama_index onto the Dagster code server boot path
metadata:
  type: project
---

`config/settings.py`가 `pipeline/steps/chunk.py`의 타입(`ChunkStrategy`)을 모듈 레벨에서 import하면
두 가지 문제가 있다:

1. **순환 임포트**: `pipeline/steps/*.py`는 거의 전부 `from rag_api.config.settings import
   resolve_settings`를 모듈 레벨에서 하므로 `settings.py`가 역방향으로 step 모듈을 import하면
   방향이 뒤집힌다.
2. **import 무게**: `chunk.py`는 모듈 최상단에서 `from llama_index.core import Document/BaseNode`를
   한다. `settings.py`는 사실상 모든 모듈이 의존하는 최하위 계층이라, 이 엣지 하나가
   `rag_api.defs.definitions`(Dagster `code-server start -m` 타깃) 부팅 경로에 llama_index 전체
   import 트리를 얹는다. 컨테이너는 `PYTHONDONTWRITEBYTECODE=1`이라 매 기동마다 소스 재컴파일 —
   콜드 컴파일이 gRPC health probe를 막아 pod 재시작 루프가 됐다 (2026-09-04).

**현재 상태 (2026-09-04)**: `ChunkStrategy`는 의존성 0인 leaf 모듈
`pipeline/steps/chunk_types.py`로 분리됨. `settings.py`와 `chunk.py` 모두 거기서 import하고,
`chunk.py`는 하위 호환용으로 재노출한다. `import rag_api.defs.definitions` 시 llama_index가
`sys.modules`에 안 뜨는 것을 유지 조건으로 본다.

**How to apply**: `settings.py`가 `pipeline/`·`rag/`·`query/`(= llama_index를 모듈 레벨에서
import하는 계층)의 타입을 필드 어노테이션에 쓰고 싶으면, 그 타입을 의존성 없는 leaf 모듈로
빼서 양쪽이 거기서 import하게 한다 (`chunk_types.py` 패턴). `settings.py` 쪽을 지연 import로
돌리는 건 안 됨 — `Literal` 타입이 클래스 필드 어노테이션에 즉시 필요하다.

관련: 코드 서버 부팅에는 `defs/` 트리의 `pipeline.steps.*` import가 전부 op 함수 본문으로
지연돼 있어야 한다 — 모듈 레벨로 새면 이 엣지가 재발한다. `Dockerfile`의 빌드 타임
`.pyc` 프리컴파일(`UV_COMPILE_BYTECODE=1` + `compileall`)이 콜드 스타트 배수를 없앤다.
