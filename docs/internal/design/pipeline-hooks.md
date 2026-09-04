# 파이프라인 훅 — 신규 문서 유입 지점 확장

> 관련: [multi-source-ingest.md](multi-source-ingest.md), [connector-state-flow.md](connector-state-flow.md), [settings-composition.md](settings-composition.md)
> 구현: US-51 ([backlog](../../../.claude/backlogs/US-51-pipeline-hooks-before-doc-create.md), [plan 51](../../../.claude/plans/51-pipeline-hooks-before-doc-create.md))

인제스트 파이프라인이 **새 문서 row를 만들기 직전**에 외부 콜백을 실행할 수 있는 등록 기반
훅을 둔다. rag-api는 콜백이 무슨 일을 하는지 알지 못한다 — 훅이 예외를 던지면 그 문서의
유입을 중단하고, 아니면 그대로 진행한다. 첫 소비자는 vendoring 앱(rag-ent-api)의 KB 문서
개수 상한이지만, 감사 로깅·태깅·메트릭·정책 거부 등 다른 용도도 같은 API를 쓴다.

## 1. 배경 (요약)

문서 개수 제한 같은 정책은 rag-api가 아니라 vendoring 앱이 소유한다([settings-composition.md]
의 원칙). 그런데 문서가 KB에 들어오는 경로는 커넥터 3종(web/confluence/github)과 업로드
2종(단건/배치)으로 흩어져 있고, 전부 `create_doc()` 호출로 수렴하지만 그 앞뒤 로직(변경 감지,
S3 스테이징)은 경로마다 다르다. vendoring 앱이 각 경로를 오버라이드하는 대신, rag-api가
"새 문서가 생성되려 한다"는 이벤트를 한 지점에서 발화하고 앱이 콜백을 붙이게 한다.

등록을 특정 프레임워크 생명주기(FastAPI startup 등)에 강제로 묶지 않는 이유는
[parser-registry.md](parser-registry.md)와 같다 — 진입점이 여러 개다. 다만 이 훅은 지연 로드
대상이 아니라 명시적 `register()` 호출로만 채워지며, 아무도 등록하지 않은 프로세스(CLI 등)에서는
`emit()`이 무연산이다.

## 2. 구조

### 2.1 클래스·모듈 관계

```
                        ┌──────────────────────────────────────────────────────┐
                        │                  rag_api/hooks.py                     │
                        │                                                      │
   register(evt, cb) ──►│  _registry: dict[type, list[Callable[[Event], None]]] │
 unregister(evt, cb) ──►│                                                      │
                        │  emit(event) ──► for cb in _registry.get(type(event)):│
                        │                      cb(event)   # 등록 순서, 예외 전파 │
                        │                                                      │
                        │  class HookAbort(Exception)          # 의도적 중단     │
                        │  @dataclass(frozen=True) BeforeDocCreate:             │
                        │      kb_id: str                                       │
                        │      principal: Any = None    # rag-api는 안 들여다봄  │
                        │      source_type: str | None = None                   │
                        └───────▲───────────────────────────────▲──────────────┘
                     emit(BeforeDocCreate)              register(BeforeDocCreate, cb)
                                │                                │
        ┌───────────────────────┴───────────┐        ┌───────────┴─────────────────────┐
        │ 생산자 — rag-api 내부, 신규 문서마다 │        │ 소비자 — vendoring 앱 startup     │
        │                                   │        │                                 │
        │  WebConnector._process_page       │        │  rag_ent: _enforce_doc_quota(ev) │
        │  ConfluenceConnector._process_page│        │    ev.principal 검사 →           │
        │  ConfluenceConnector._process_attachment   │    KB 문서 수 >= 상한이면        │
        │  GitHubConnector._process_file    │        │    raise IngestQuotaError        │
        │  docs.upload_doc                  │        │         (HookAbort 상속)         │
        │  docs.upload_docs_batch           │        └─────────────────────────────────┘
        └───────────────┬───────────────────┘
                        │ HookAbort (또는 서브클래스) 전파
                        ▼
        ┌───────────────────────────────────────────────────────────────┐
        │ 포획 지점                                                       │
        │   connectors._run_sync : except HookAbort                       │
        │       → set_connector_sync_status(idle) + last_error 경고        │
        │         (status="error" 아님 — 정상 종료로 취급)                  │
        │   docs.upload_docs_batch : 차단 파일 1건 error 기록 + 남은 파일     │
        │       skipped 처리 후 break → BatchUploadError(by_hook=True) →      │
        │       app.py → HTTP 403 (본문에 results + detail 유지)              │
        │   docs.upload_doc        : 전파 → app.py 예외 핸들러 → HTTP 403    │
        └───────────────────────────────────────────────────────────────┘
```

핵심:

- 모듈은 최상위 `rag_api/hooks.py`에 둔다 — `emit()` 호출부가 전부 `pipeline/` 밖(`connectors/`,
  `api/routers/`)이고 `pipeline/` 내부에서 import하지 않으므로, `exceptions.py`처럼 cross-cutting
  최상위 모듈로 취급한다(문서 파일명 `pipeline-hooks.md`는 유지).
- `hooks.py`는 **레지스트리 + 이벤트 타입 + `HookAbort`만** 소유한다. 커넥터/라우터를 import 하지
  않는다(역방향 의존만).
- 생산자는 `emit()`을, 소비자는 `register()`를 호출한다. 서로 직접 참조하지 않는다.
- `principal`은 `Any`다. rag-api는 값을 전달만 하고 해석하지 않는다. vendoring 앱이 자기 타입
  (`CurrentUser` 등)을 넣고 자기 콜백에서 downcast 한다.
- `HookAbort`는 rag-api가 정의하지만, 실제로 던지는 건 소비자의 서브클래스다. 포획 지점은
  구체 타입이 아니라 `HookAbort`를 잡는다.

### 2.2 컴포넌트

| 컴포넌트 | 위치 | 역할 |
|---|---|---|
| 레지스트리 상태 | `rag_api/hooks.py` `_registry` | 이벤트 타입 → 콜백 리스트. 모듈 전역 |
| 등록 API | `register()` / `unregister()` | 레지스트리를 변경하는 유일한 통로 |
| 발화 API | `emit(event)` | `type(event)`에 등록된 콜백을 등록 순서대로 실행 |
| 이벤트 타입 | `BeforeDocCreate` | 신규 문서 생성 직전 페이로드 (kb_id, principal, source_type) |
| 중단 예외 | `HookAbort` | 콜백이 "이 동작을 의도적으로 멈춘다"고 알리는 기저 예외. 서브클래싱 가능 |
| 생산자 | 커넥터 3종 + `docs.py` 업로드 2종 | 신규 `create_doc` 직전에 `emit(BeforeDocCreate(...))` |
| 포획자 | `connectors._run_sync`, `docs.upload_docs_batch` | `HookAbort`를 잡아 경로별로 처리 (배치는 `BatchUploadError`로 재raise → 403, 단일 업로드는 전파 → 403) |

### 2.3 이벤트: `BeforeDocCreate`

발화 조건 — **`get_doc_by_source()`가 `None`을 반환해 "새 문서"가 확정된 직후, `create_doc()`
호출 직전.** 다음은 발화하지 않는다:

- 기존 문서의 재-sync (변경분 갱신, `set_fetching`/`set_staged` 경로)
- 변경 없는 문서 skip
- fetch 실패로 `status="failed"` row를 만드는 경로 (web `_process_page`의 예외 분기) — 에러
  기록이라 게이트 대상 아님

| 필드 | 타입 | 설명 |
|---|---|---|
| `kb_id` | `str` | 대상 KB |
| `principal` | `Any` | 유입을 유발한 주체. HTTP 경로는 `request.state.ingest_principal`, 없으면 `None` |
| `source_type` | `str \| None` | `"web"` / `"confluence"` / `"github"` / `"s3"` |

### 2.4 emit 호출 지점

| 파일 | 함수 | 비고 |
|---|---|---|
| `connectors/web.py` | `_process_page` | 정상 스테이징 경로의 `create_doc` 직전 (fetch-fail 분기 제외) |
| `connectors/confluence.py` | `_process_page` | 페이지 `create_doc` 직전 |
| `connectors/confluence.py` | `_process_attachment` | 첨부 `create_doc` 직전 |
| `connectors/github.py` | 파일 처리 메서드 | `create_doc` 직전 |
| `api/routers/docs.py` | `upload_doc` | `existing is None` 분기 |
| `api/routers/docs.py` | `upload_docs_batch` | 루프 내 `existing is None`; `HookAbort` 포획 → 차단 파일 기록 + 나머지 skipped 후 `BatchUploadError` |

> 커넥터 4곳의 스테이징 시퀀스(get_doc_by_source → 변경 감지 → create_doc → S3 → set_staged
> → enqueue)는 사실상 중복이다. 이를 공통 베이스로 추출하면 `emit` 호출도 한 곳으로 모이지만,
> 그건 이 훅과 독립된 커넥터 리팩터라 별도 backlog로 다룬다(§6).

### 2.5 principal 관통 경로

```
OIDC 미들웨어 (vendoring 앱)
  request.state.ingest_principal = <앱 정의 값>          # rag-api 단독 배포면 미설정 → None
        │
        ├─ POST /kb/{id}/docs/upload ───────► emit(BeforeDocCreate(kb_id, principal, "s3"))
        │
        ├─ POST /kb/{id}/docs/upload/batch ─► (파일 루프) emit(BeforeDocCreate(kb_id, principal, "s3"))
        │
        └─ POST /connectors/{id}/sync
               principal = getattr(request.state, "ingest_principal", None)   # 스케줄 시점 캡처
               background_tasks.add_task(_run_sync, connector, principal=principal)
                     │
                     ▼   (응답 이후, 백그라운드)
               _run_sync(connector, principal)
                     │   _dispatch_sync(connector, principal)
                     ▼
               XConnector(...).sync(kb_id, connector_id, principal=principal)
                     │   self._principal = principal
                     ▼   (커넥터 루프, 신규 문서마다)
               emit(BeforeDocCreate(kb_id, self._principal, self.source_type))
```

`request.state`는 백그라운드 태스크로 넘어가지 않으므로, 커넥터 sync는 **스케줄 시점**에
`principal`을 평범한 값으로 읽어 `add_task` 인자로 캡처한다. 이후 `_run_sync` →
`_dispatch_sync` → `.sync()` → 인스턴스 필드로 관통한다.

### 2.6 `HookAbort` 처리

`_run_sync`는 현재 `except Exception`으로 모든 예외를 `connector.status="error"`로 만든다.
`except HookAbort`를 그 **앞에** 두어, 훅에 의한 중단은
`set_connector_sync_status(connector_id, "idle", last_error=str(e))` 한 번으로만 남기고
`set_connector_status(..., "error")`는 호출하지 않는다(커넥터 `status` 불변). 중단 시점 이전에
이미 커밋된 문서(`create_doc`+`enqueue`가 반복마다 개별 커밋)는 그대로 유지된다.

`set_connector_sync_status`에 `last_error: str | None = None` 선택 인자를 추가했다 — 값이 주어지면
`last_error`만 갱신하고 `status`는 건드리지 않는다(커넥터 `last_error`만 세팅하는 기존 함수가
없었음). Dagster 스케줄 경로(`connector_sync_op`)는 이 인자를 넘기지 않으므로 동작 불변.

### 2.7 배치 업로드의 실패 처리 (US-52)

`upload_docs_batch`는 파일을 전부 순회하며 항목별 결과를 `results`에 모은다
(collect-and-continue).

- `except (IngestValidationError, ClientError)`: 그 파일만 `{title, error, status:"error"}`로
  기록하고 다음 파일로 계속.
- `except HookAbort`: 이후 파일이 모두 같은 훅에 걸리므로, 차단된 파일 1건을 error로 기록하고
  남은 파일은 `{error: "Skipped: batch stopped at ..."}`로 채운 뒤 `break`. `stopped_by_hook`
  플래그를 세운다.
- 두 분기 모두 `detail = detail or str(e)` 로 **첫 실패 사유**를 한 번만 캡처한다(대표 메시지).

루프 후 `results`에 실패 항목이 있으면
`BatchUploadError(results, detail, by_hook=stopped_by_hook)`를 raise한다. `api/app.py` 핸들러가
`by_hook`에 따라 `403`(훅 중단, 단일 업로드와 동일) 또는 `422`(형식/스토리지)로 매핑하고,
본문은 `{results: [...], detail: "<한 줄 사유>"}` — 성공 항목의 `doc_id`/`status_url`과 UI용
대표 메시지를 모두 보존한다. 전부 성공하면 `{results: [...]}` + `202`. HTTP status 결정은
`05-exception-handling.md` 규칙대로 `app.py`에만 둔다.

예전에는 `HookAbort`를 잡아 남은 파일 전부를 같은 error 문자열로 채운 뒤 `202`를 반환했다 —
상태 코드만 보는 소비자가 실패를 놓치고, 시도되지 않은 파일까지 개별 차단된 것처럼 보였다.
`by_hook` 분기와 `detail`, skipped 표기가 그 두 문제를 해소한다.

## 3. API (시그니처만 — 구현 없음)

```python
# rag_api/hooks.py
from dataclasses import dataclass
from typing import Any, Callable

from rag_api.exceptions import HookAbort  # 정의는 exceptions.py, 여기서 재노출


@dataclass(frozen=True)
class BeforeDocCreate:
    kb_id: str
    principal: Any = None
    source_type: str | None = None


def register(event_type: type, callback: Callable[[Any], None]) -> None: ...
def unregister(event_type: type, callback: Callable[[Any], None]) -> None: ...
def emit(event: Any) -> None: ...
```

> `HookAbort`는 `.claude/rules/conventions/05-exception-handling.md`의 "모든 예외 클래스는
> `src/rag_api/exceptions.py`에만 정의" 하드 룰에 따라 `exceptions.py`에 둔다(`RAGError` 미상속 —
> 레이어별 HTTP 매핑과 별개 축). `hooks.py`가 `__all__`로 재노출하므로 공개 API
> `from rag_api.hooks import HookAbort`는 그대로다. 같은 `(event_type, callback)` 쌍을
> 중복 `register()`하면 무시된다.

## 4. 실행 계약

- **순서**: 콜백은 `register()` 호출 순서대로 실행된다.
- **예외 전파**: 콜백이 던진 예외(`HookAbort`든 아니든)는 `emit()` 밖으로 그대로 전파된다.
  이후 콜백은 실행되지 않는다. `emit()`은 예외를 삼키지 않는다.
- **동기 실행**: `emit()`은 호출자 스레드에서 동기로 돈다. 콜백은 인제스트 경로에 직접
  얹히므로 가볍게 유지해야 한다(예: 카운트 쿼리 1회). 무거운 작업은 콜백이 큐잉해야 한다.
- **미등록**: `_registry`에 항목이 없으면 `emit()`은 즉시 반환한다(무연산). rag-api 단독
  배포의 기본 상태.
- **재진입 금지**: 콜백에서 다시 `emit()`을 부르거나 `register()`/`unregister()`를 호출하는
  경우는 지원하지 않는다.

## 5. vendoring 앱 연동 (rag-ent-api 예시)

```python
# rag_ent/exceptions.py
from rag_api.hooks import HookAbort
class IngestQuotaError(HookAbort): ...

# rag_ent 앱 startup
from rag_api.hooks import register, BeforeDocCreate
register(BeforeDocCreate, _enforce_doc_quota)

def _enforce_doc_quota(ev: BeforeDocCreate) -> None:
    user = ev.principal                         # CurrentUser | None
    if user is not None and user.is_super_admin:
        return
    max_docs = get_settings().authz.max_docs_count
    if max_docs and _kb_doc_count(ev.kb_id) >= max_docs:
        raise IngestQuotaError(f"KB document limit reached: .../{max_docs}")

# OIDC 미들웨어: request.state.current_user 세팅 옆에
request.state.ingest_principal = user
```

per-user / per-group 쿼터로 확장할 때 `ev.principal`에 이미 `user_id`·`groups`가 실려 있으므로
rag-api 변경은 없다.

## 6. 비목표 / 향후

- **커넥터 스테이징 통합 리팩터** — web/confluence/github의 중복 스테이징 시퀀스를 공통
  베이스(`_process_item` 류)로 추출. 중복 제거 그 자체로 가치 있으나 이 훅과 독립적이다.
  별도 backlog.
- **sync 라이프사이클 훅** (`BeforeConnectorSync` / `AfterConnectorSync`) — 발화 단위가
  문서가 아니라 sync 실행 1회다. 레지스트리는 그대로 지원하므로 필요 시 이벤트 dataclass만
  추가하고 `_run_sync`/`_dispatch_sync`에서 `emit`한다.
- **per-user / per-group 쿼터** — 소비자(vendoring 앱) 몫. 배선은 `principal`로 이미 완료.
- **CLI (`rag-api ingest`) 게이팅** — CLI 프로세스는 아무 콜백도 등록하지 않으므로 자동
  무연산. 게이팅이 필요하면 그 진입점에서 `register()`를 호출해야 한다.
