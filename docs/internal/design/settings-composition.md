# Settings 확장 아키텍처

순수 기술 설계 문서 — 특정 PRD 섹션에 대응되지 않는다(요건 없음). rag-api를 editable path
dependency로 vendoring하는 앱(rag-ent-api 등)이 `Settings`를 안전하게 확장하기 위한 기본
설계를 정의한다.

## 1. 목표

**문제**: 지금은 "누가 먼저 `get_settings()`를 부르는가"라는 우연에 따라 결과가 갈리는 암묵적
레이스 컨디션이 있다. vendoring 앱(rag-ent-api)이 자신의 확장 `Settings` 서브클래스를
등록하기 전에 rag-api 자체 코드가 먼저 `get_settings()`를 부르면, rag-api는 자기 기본
`Settings`로 먼저 인스턴싱해버리고, 그 인스턴스는 나중에 vendoring 앱이 `_settings` 전역
변수를 직접 덮어쓰는 방식("bridge")으로 폐기된다. 같은 `settings.yaml`이 프로세스 하나당
최대 3번(rag-api 기본 인스턴스 1회 + vendoring 앱의 재사용 호출 1회 + vendoring 앱 자체 raw
읽기 1회) 중복 파싱되고, 어느 진입점이 먼저 실행되느냐에 따라 동작이 달라질 여지가 생긴다.

```
[개선 전] 우연에 의존하는 이중 인스턴싱 + 사후 패치

  rag-api 코드 경로              vendoring 앱 코드 경로
  (예: parser registry)          (예: 플러그인 register())
        │                              │
        ▼                              │
  get_settings() 최초 호출              │
        │                              │
        ▼                              │
  Settings.from_yaml()                 │
  (rag-api 기본 클래스,                 │
   settings.yaml 1차 파싱)              │
        │                              │
        ▼                              ▼
  _settings 캐시(임시)          get_settings() 최초 호출
        │                              │
        │                              ▼
        │                      확장 Settings.from_yaml()
        │                      ├─ RagApiSettings.from_yaml() 재호출 (2차 파싱)
        │                      └─ raw yaml 재오픈 (3차 파싱)
        │                              │
        │                              ▼
        │                      확장 Settings 인스턴스 완성
        │                              │
        └────────── 덮어씀 ◄───────────┘
        (rag-api._settings를 확장 인스턴스로 사후 교체)

  → 어느 경로가 먼저 실행되는지에 따라 중간 상태 존재, 파일 3중 파싱, 진입점마다 재현 필요


[개선 후] 단일 인터페이스 + 최초 1회 명시적 인스턴싱 + 전체 공유

  프로세스 진입점 (앱 소유, rag-api 진입점을 직접 쓰지 않음)
        │
        ▼
  vendoring 앱이 get_settings()를 "가장 먼저" 호출
  (CLI/FastAPI든 Dagster code server든 — 앱이 소유한 thin entrypoint에서)
        │
        ▼
  raw dict 로딩 1회 (RagApiSettings._load_raw 재사용, 파일 파싱 1회만)
        │
        ▼
  확장 Settings.model_validate(raw) — 검증 1회
        │
        ▼
  rag_api.config.settings.set_settings(instance)  ← 명시적 주입 API
        │
        ▼
  이후 rag-api/vendoring 앱 어디서 get_settings()를 불러도 동일 인스턴스 반환
  (레이스 컨디션 없음 — "누가 먼저 부르는가"가 코드로 고정됨)
```

## 2. 인터페이스 구성

확장 가능한 계약은 딱 두 가지뿐이다.

```python
class Settings(BaseModel):
    ...  # rag-api 기본 섹션들

def get_settings() -> Settings: ...      # 읽기 — 항상 동일 인스턴스 반환
def set_settings(instance: Settings) -> None: ...  # 쓰기 — 최초 1회만 의미 있음(아래 §5)
```

`Settings`를 상속해 필드를 추가하는 것, `get_settings()`가 항상 프로세스 전역에서 동일한
하나의 인스턴스를 반환하는 것 — 이 두 가지만 지키면 rag-api 내부 코드(`infra/`, `pipeline/`,
`registry.py` 등)는 자신이 부르는 `get_settings()`가 확장된 것인지 신경 쓸 필요가 없다.
`Settings`가 갖지 않는 필드(vendoring 앱이 추가한 것)에 접근하는 코드는 vendoring 앱 쪽에만
존재하므로 타입 경계도 자연히 지켜진다.

## 3. 기본 구성 (rag-api 단독 실행)

```python
# rag_api/config/settings.py
_APP_SETTINGS_PATH = Path("/app/settings.yaml")
_SETTINGS_PATH = (
    _APP_SETTINGS_PATH if _APP_SETTINGS_PATH.exists()
    else Path(__file__).parents[3] / "settings.yaml"
)

_settings: Settings | None = None

def _load_raw(path: Path = _SETTINGS_PATH) -> dict[str, Any]:
    """yaml 파일 읽기 + 환경변수 오버라이드 적용, 검증 이전의 raw dict 반환."""
    data = yaml.safe_load(open(path)) if path.exists() else {}
    if api_key := os.environ.get("OPENAI_API_KEY"):
        data.setdefault("provider", {})["openai_api_key"] = api_key
    # ... 기존 환경변수 오버라이드 전부 이 함수로 이동
    return data

class Settings(BaseModel):
    ...
    @classmethod
    def from_yaml(cls, path: Path = _SETTINGS_PATH) -> Settings:
        return cls.model_validate(_load_raw(path))

def set_settings(instance: Settings) -> None:
    global _settings
    _settings = instance

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_yaml()
    return _settings
```

rag-api 혼자 실행될 때는 `set_settings()`를 아무도 안 부르므로 `get_settings()`가 최초 호출
시 `Settings.from_yaml()`로 자기 자신을 구성한다 — 지금과 동작 동일, 변경 없음.

`_load_raw()`를 분리하는 이유는 §5에서 vendoring 앱이 env override 로직을 중복 없이
재사용하기 위해서다.

## 4. 확장 (vendoring 앱)

vendoring 앱이 지켜야 할 것은 딱 하나 — **자신의 코드가 rag-api 코드보다 먼저 실행되는
진입점을 프로세스마다 스스로 소유**하는 것이다. "언젠가 rag-api 쪽에서 먼저
`get_settings()`가 호출될 수도 있다"는 가능성 자체를 프로세스 구조로 차단한다.

- FastAPI 서버처럼 vendoring 앱이 직접 만든 진입점(CLI `serve` 커맨드 등)은 이미 자연스럽게
  앱 코드가 먼저 실행되므로 문제 없음.
- Dagster code server처럼 **rag-api 모듈을 진입점으로 직접 지정하는 경우**(`dagster
  code-server start -m rag_api.defs.definitions`)가 취약점이다 — 이 경우 vendoring 앱은
  자신만의 thin wrapper 모듈을 만들어 그걸 진입점으로 바꿔야 한다(§6 예시).

## 5. 설정 방법

1. `RagApiSettings._load_raw(path)`를 호출해 raw dict를 한 번만 얻는다(파일 파싱 1회).
2. vendoring 앱 자신의 섹션(`oidc`, `image_captioning` 등)을 그 dict에 병합한다.
3. vendoring 앱 자신의 환경변수 오버라이드를 적용한다.
4. 확장 `Settings` 서브클래스로 **한 번만** 검증한다(`model_validate`).
5. `rag_api.config.settings.set_settings(instance)`를 호출해 명시적으로 주입한다 — 이제
   프로세스 전체에서 `rag_api.config.settings.get_settings()`와 vendoring 앱의
   `get_settings()`가 동일 인스턴스를 반환한다.
6. 이 순서를 프로세스가 시작되자마자, rag-api의 어떤 코드보다도 먼저 실행되는 곳(§4의 thin
   entrypoint)에 둔다.

## 6. 예시 (rag-ent-api 기준)

```python
# rag_ent/config/settings.py
from rag_api.config.settings import Settings as RagApiSettings
from rag_api.config.settings import _load_raw, set_settings

class Settings(RagApiSettings):
    oidc: OidcSettings = Field(default_factory=OidcSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)  # image_captioning 등 확장 포함
    # ...

    @classmethod
    def from_yaml(cls, path: Path = _SETTINGS_PATH) -> Settings:
        raw = _load_raw(path)  # 파일 파싱 1회만 — rag-api 로직 재사용
        if extra_key := os.environ.get("OIDC_ADMIN_CLIENT_SECRET"):
            raw.setdefault("oidc", {})["admin_client_secret"] = extra_key
        return cls.model_validate(raw)

_settings: Settings | None = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_yaml()
        set_settings(_settings)  # rag-api 쪽 슬롯에도 명시적으로 등록
    return _settings
```

```python
# rag_ent/defs/definitions.py — Dagster code server 진입점 (신규)
"""dagster code-server -m rag_ent.defs.definitions 로 실행 — rag_api.defs.definitions를
직접 진입점으로 쓰지 않는 이유: get_settings()가 rag-api 코드보다 먼저 실행되어야 하기
때문(§4)."""

from rag_ent.config.settings import get_settings

get_settings()  # rag-api 쪽 코드가 실행되기 전에 먼저 주입 완료

from rag_api.defs.definitions import defs  # noqa: E402  (주입 이후에 import)

__all__ = ["defs"]
```

```yaml
# docker-compose.yml
dagster-rag-api:
  command: dagster code-server start -h 0.0.0.0 -p 4000 -m rag_ent.defs.definitions
```

FastAPI 진입점(`rag_ent/main.py`)은 이미 `_setup()`에서 `get_settings()`를 가장 먼저
부르므로 변경 불필요 — Dagster 진입점만 이 패턴이 새로 필요하다.
