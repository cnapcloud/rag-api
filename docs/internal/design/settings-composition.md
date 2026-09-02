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
        data.setdefault("provider", {})["api_key"] = api_key
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

## 7. provider 일반화 (US-50)

`ProviderSettings`는 벤더 전용 필드를 두지 않고 **프로토콜(`name`) + 주소(`url`) + 인증
(`api_key`)** 세 필드만 갖는다. 새 호스팅 임베딩 백엔드 추가가 `settings.yaml` 수정만으로
끝나게 하는 것이 목적이다.

```python
class ProviderSettings(BaseModel):
    name: str = "ollama"   # ollama / openai / jina / 그 외
    url: str = ""          # 빈 값 = 그 provider의 기본 엔드포인트
    api_key: str = ""
```

세 필드 모두 기본값이 있어 `provider` 블록을 통째로 생략하면 로컬 compose Ollama
(`http://ollama:11434`, 인증 없음)와 완전히 동일하게 동작한다.

### 7.1 `resolve_provider_conn()` — 필드명을 아는 유일한 지점

```python
class ProviderConn(BaseModel):   # frozen
    base_url: str | None         # None = 클라이언트 SDK 기본 엔드포인트
    api_key: str | None

def resolve_provider_conn(provider: ProviderSettings) -> ProviderConn: ...
```

`rag_api.config.settings` 공개 경로로 노출된다. 임베딩 팩토리(`pipeline/steps/embed.py`) ·
`/ready`(`api/routers/health.py`) · rag-ent-api 캡셔닝(E-31)이 모두 이 헬퍼만 거쳐 provider에
접근한다 — `name` / `url` / `api_key`라는 필드명을 아는 코드가 두 저장소 통틀어 이 함수 하나뿐이
되게 한다. 새 provider 필드가 생기면 이 함수와 `ProviderConn`만 고치면 된다.

해석 규칙 (`name`은 정규화하지 않고 그대로 비교한다 — 빌트인 3종은 `settings.yaml`에 정확히
소문자 `ollama` / `openai` / `jina`로 적어야 하고, 그 외 값은 표기 그대로 `/ready` 응답·`checks`
키·임베딩 메타데이터에 쓰인다):

| `name` | `base_url` (`url`이 빈 값일 때) | `api_key` |
|--------|-------------------------------|-----------|
| `ollama`(또는 빈 값) | `http://ollama:11434` | 없음(None) |
| `openai` / `jina` / 미지 | `None`(SDK 기본) | `provider.api_key` |

### 7.2 `url` 이원화 — Ollama는 bare host, OpenAI 호환은 `/v1` 포함

- Ollama: `url`은 스킴+호스트만(`http://gpu-box:11434`). LlamaIndex `OllamaEmbedding`이 경로를
  붙인다.
- OpenAI 호환: `url`은 `/v1`을 포함한 완전한 base URL(`http://vllm:8000/v1`). `/embeddings`는
  클라이언트가 붙인다.

`/v1` 누락 자동 보정은 하지 않는다(US-50 결정). root-mount 서버(`/embeddings`를 루트에 노출)에서
자동 append가 오히려 깨지므로, 문서와 `settings.yaml` 주석으로만 고정한다.

### 7.3 미지 `name` → OpenAI 호환 폴백

`name`이 `ollama` / `openai` / `jina` 중 어느 것도 아니면 **에러가 아니라**
`llama-index-embeddings-openai-like`의 `OpenAILikeEmbedding`으로 처리한다(vLLM, Text Embeddings
Inference, Gemini OpenAI 호환 레이어 등). 이때:

- `url`을 필수로 요구한다(커스텀 주소이므로 없으면 `ConfigError`).
- `provider`를 인식하지 못해 폴백한다는 `WARNING` 로그를 한 줄 남긴다 — `ollamaa` 같은 오타가
  조용히 404로 새는 것을 눈에 띄게 하기 위함(US-50 결정: `INFO`가 아니라 `WARNING`).
- `api_key`가 비어 있으면 무해한 placeholder(`sk-no-auth`)를 자동 주입한다(SDK가 빈 키를
  거부하지만 인증 없는 자체 호스팅 서버는 값을 무시).

### 7.4 모델명 enum 우회, 차원 미전달

`openai` 본가도 `OpenAIEmbedding`이 아니라 `OpenAILikeEmbedding`을 쓴다 — `model` 인자의 enum
검증을 우회해 최신/미등록 모델명도 그대로 통과시키기 위함. `url`이 비면 `api_base`를
`https://api.openai.com/v1`로 채운다.

임베딩 클라이언트에 `dimensions`(차원 수)를 전달하지 않는다(US-50 결정). `embedding.vector_size`
는 Qdrant 컬렉션 벡터 크기 지정 전용으로만 쓰고, 모델이 반환하는 네이티브 차원을 그대로
받는다 — 운영자가 둘을 일치시킬 책임이다(항상 전달하면 `ada-002`처럼 차원 지정을 지원하지 않는
모델에서 에러가 나기 때문).

### 7.5 Jina는 네이티브 — query/passage task 비대칭

`jina`는 OpenAI 호환 경로가 아니라 네이티브(`llama-index-embeddings-jinaai`)로 붙인다.
인제스트(passage)와 검색(query)이 서로 다른 `task` 값(`retrieval.passage` /
`retrieval.query`)으로 나가야 검색 품질이 유지되기 때문이다. 해당 패키지는 `task`를 방향과
무관하게 단일 값으로 보내므로, `embed.py`에서 방향별 메서드(`_get_query_embedding` /
`_get_text_embeddings`)를 오버라이드해 task를 강제하는 얇은 서브클래스를 쓴다. Gemini 등 다른
비대칭 벤더를 OpenAI 호환 경로로 붙이면 이 비대칭은 손실된다(각각 별도 US로 네이티브 분기 추가).
