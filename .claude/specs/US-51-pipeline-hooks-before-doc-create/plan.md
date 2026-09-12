# Plan 51: 파이프라인 훅 — 신규 문서 생성 직전 등록 기반 콜백

- 상태: done
- Backlog: [US-51](../backlogs/US-51-pipeline-hooks-before-doc-create.md)
- 설계: [pipeline-hooks.md](../../../docs/internal/design/pipeline-hooks.md)

## 설계 대비 확정 사항 (구현 중 결정)

0. **모듈 위치** — 설계 문서는 `pipeline/hooks.py`로 적었으나 최상위 `rag_api/hooks.py`로 둔다.
   `emit()` 호출부가 전부 `pipeline/` 밖(`connectors/`, `api/routers/docs.py`)이고 `pipeline/`
   내부에서 import하지 않으므로 `exceptions.py`처럼 cross-cutting 최상위 모듈로 취급
   (사용자 결정, 2026-09-03). 설계 §2.1/§2.2/§3 갱신, 문서 파일명 `pipeline-hooks.md`는 유지.

1. **`HookAbort` 정의 위치** — 설계 §2.1/§3은 `hooks.py`가 소유한다고 적었으나,
   `.claude/rules/conventions/05-exception-handling.md`의 "모든 예외 클래스는
   `src/rag_api/exceptions.py`에만 정의" 하드 룰이 우선한다. 따라서:
   - `exceptions.py`에 `HookAbort(Exception)` 정의 (`RAGError`를 상속하지 **않음** — 레이어별
     HTTP 매핑 축과 별개. vendoring 앱이 자유롭게 서브클래싱하고 포획 지점은 구체 타입이 아닌
     `HookAbort`만 잡는다).
   - `rag_api/hooks.py`는 `from rag_api.exceptions import HookAbort` 후 `__all__`에 재노출.
     설계의 공개 API(`from rag_api.hooks import HookAbort`)는 그대로 유지된다.
   - `pipeline-hooks.md` §3에 "정의는 exceptions.py, hooks.py는 재노출" 주석 추가.

2. **커넥터 sync의 `HookAbort` 처리 시 `last_error`** — 설계 §2.6은 `sync_status="idle"` +
   `last_error` 경고를 남긴다고 했다. 커넥터 `last_error`만 세팅하는 기존 함수가 없으므로
   `set_connector_sync_status()`에 `last_error: str | None = None` 선택 인자를 추가한다(추가만,
   하위 호환). 이 함수가 이미 sync 라이프사이클 필드(`sync_started_at`, `last_synced_at`)를
   관리하므로 sync 종료 메모를 함께 쓰는 것은 자연스럽다. `status`는 건드리지 않는다.

3. **HTTP 핸들러의 `principal` 취득** — `upload_doc` / `upload_docs_batch` / `trigger_sync`에
   `request: Request` 파라미터를 추가하고 `getattr(request.state, "ingest_principal", None)`로
   읽는다. `tracing/span.py`의 `_is_unserializable_kwarg()`에 `Request`를 추가해 span
   `input.value`에 Request 객체가 직렬화되지 않게 한다.

## 작업 순서

### 1. `exceptions.py` — `HookAbort` 추가
- `class HookAbort(Exception)` 추가. docstring 영어. `RAGError` 미상속.

### 2. `rag_api/hooks.py` — 신규 모듈
```python
_registry: dict[type, list[Callable[[Any], None]]] = {}

def register(event_type, callback) -> None      # append (중복 등록 허용 안 함: 이미 있으면 skip)
def unregister(event_type, callback) -> None     # 있으면 제거, 없으면 no-op
def emit(event) -> None                           # _registry.get(type(event), []) 복사본 순회, 예외 전파
def _reset() -> None                              # 테스트 전용, _registry.clear()

@dataclass(frozen=True)
class BeforeDocCreate:
    kb_id: str
    principal: Any = None
    source_type: str | None = None

from rag_api.exceptions import HookAbort  # re-export
__all__ = ["BeforeDocCreate", "HookAbort", "emit", "register", "unregister"]
```
- 커넥터/라우터 import 금지. `logging.getLogger(__name__)` 선언(등록/해제 시 debug 로그).
- `register`: 같은 (event_type, callback) 재등록은 무시(로그 debug) — 재진입/중복 방지.

### 3. `infra/postgres.py` — `set_connector_sync_status` 확장
- 시그니처: `set_connector_sync_status(connector_id, sync_status, last_synced_at=None, last_error=None)`.
- `last_error is not None`이면 `last_error = %s` SET 절 추가(값 `[:500]`).
- 수정 전 파일 Read 완료(하드 룰 4). `_run_sync`/`connector_sync_op` 기존 호출부는 인자 미전달로
  동작 불변.

### 4. `tests/conftest.py` — Fake 갱신
- `FakePostgresStore.set_connector_sync_status`에 `last_error=None` 인자 추가, 세팅 반영.
- `reset_hooks` 픽스처 추가: `rag_api.hooks._reset()`를 test 전후 호출(등록 상태 격리).

### 5. 생산자 5경로에 `emit(BeforeDocCreate(...))` 삽입 — 신규 문서 확정 직후·`create_doc` 직전

| 파일 | 위치 | source_type |
|---|---|---|
| `connectors/web.py` `_process_page` | L375 `if doc is None:` 정상 스테이징 분기 (L304 fetch-fail 분기 제외) | `"web"` |
| `connectors/confluence.py` `_process_page` | L194 `if doc is None:` | `"confluence"` |
| `connectors/confluence.py` `_process_attachment` | L327 `if doc is None:` | `"confluence"` |
| `connectors/github.py` `_process_file` | L208 `if doc is None:` | `"github"` |
| `api/routers/docs.py` `upload_doc` | L67 `if existing is None:` 블록 진입 직후 | `"s3"` |
| `api/routers/docs.py` `upload_docs_batch` | L147 `if existing is None:` 블록 진입 직후 | `"s3"` |

- 커넥터: `sync(self, kb_id, connector_id, principal=None)` 시그니처에 `principal` 추가 →
  `self._principal = principal`. `_process_*`에서 `emit(BeforeDocCreate(kb_id, self._principal, "<type>"))`.
- `emit` 위치는 `create_doc(...)` **바로 앞줄**. 콜백이 `HookAbort`를 던지면 `create_doc` 미실행.

### 6. `api/routers/connectors.py` — principal 관통 + `_run_sync` HookAbort 포획
- `trigger_sync(connector_id, request: Request, background_tasks)`:
  `principal = getattr(request.state, "ingest_principal", None)` →
  `background_tasks.add_task(_run_sync, connector, principal=principal)`.
- `_run_sync(connector: dict, principal: Any = None)`: `_dispatch_sync(connector, principal=principal)`.
  `except HookAbort as e:`를 `except Exception` **앞에** 추가:
  ```python
  except HookAbort as e:
      logger.warning("Connector sync stopped by hook: connector_id=%s err=%s", connector_id, e)
      set_connector_sync_status(connector_id, "idle", last_error=str(e))
  ```
  (status 미변경. 중단 이전 커밋된 문서는 그대로 유지 — 반복마다 개별 커밋이므로 자동.)
- `_dispatch_sync(connector: dict, principal: Any = None)`: 각 `XConnector(...).sync(kb_id, connector_id, principal=principal)`.
- `defs/ops/connector_sync_op.py`의 `_dispatch_sync(connector)` 호출은 그대로(principal=None).

### 7. `api/routers/docs.py` — principal + batch HookAbort 포획
- `upload_doc(kb_id, request: Request, file)`: `if existing is None:` 진입 직후
  `emit(BeforeDocCreate(kb_id, getattr(request.state, "ingest_principal", None), "s3"))`.
  `HookAbort`는 미포획 → app.py 핸들러 → 403.
- `upload_docs_batch(kb_id, request: Request, files)`:
  - `for idx, file in enumerate(files):`로 변경.
  - `if existing is None:` 진입 직후 `emit(...)`.
  - per-file `try`에 `except HookAbort as e:` 추가(다른 except와 무관 — 독립 타입):
    현재 파일 결과에 `{"title", "error": str(e), "status": "error"}` append,
    `files[idx + 1:]` 각각도 동일 error entry append, `break`.

### 8. `api/app.py` — `HookAbort` → 403 핸들러
- `from rag_api.exceptions import HookAbort` (또는 `rag_api.hooks`).
- `@app.exception_handler(HookAbort)` → `JSONResponse(status_code=403, content={"detail": str(exc)})`.
  `logger.warning`로 기록. `RuntimeError` 핸들러보다 앞(등록 순서 무관하나 명확성 위해 인접 배치).

### 9. `tracing/span.py` — Request 필터
- `_is_unserializable_kwarg`에 `from starlette.requests import Request` 추가, `Request` 인스턴스 True.

### 10. 문서 갱신
- `pipeline-hooks.md`: §3에 HookAbort 정의 위치 주석, §2.6에 `set_connector_sync_status(...,
  last_error=)` 반영.
- `docs/internal/design/http-error-codes.md`: `HookAbort` → 403 행 추가 (라이브러리 예외 표가
  아니라 도메인 표 쪽 — 실제 파일 구조 확인 후 배치).
- `.claude/rules/conventions/05-exception-handling.md`: Hierarchy 다이어그램 아래에 "`HookAbort`
  (RAGError 계열 아님, 파이프라인 훅 중단용, → 403)" 한 줄. (하드 룰 파일이므로 최소 수정.)

## 테스트 계획

### `tests/unit/test_hooks.py` (신규)
- `emit` 등록 순서대로 콜백 호출 (리스트에 append하는 콜백 2개).
- 미등록 이벤트 타입 `emit` → 무연산(예외 없음).
- 콜백 예외(`HookAbort` / 일반 `RuntimeError`) → `emit` 밖으로 전파 + 이후 콜백 미호출.
- `unregister` 후 해당 콜백 미호출 / 없는 콜백 unregister 무연산.
- 같은 콜백 중복 `register` → 1회만 호출.
- `HookAbort`가 `rag_api.hooks`와 `rag_api.exceptions` 양쪽에서 import되고 동일 객체.
- import 그래프: `import rag_api.hooks`가 `rag_api.connectors`/`rag_api.api`를
  `sys.modules`에 끌어들이지 않음.

### `tests/unit/test_web_connector.py` / `test_confluence_connector.py` / `test_github_connector.py`
- 신규 문서 경로에서 `emit(BeforeDocCreate)` 1회 호출, `kb_id`/`source_type`/`principal` 값 확인
  (`sync(..., principal=sentinel)` 전달 시 sentinel 관통).
- 콜백이 `HookAbort` 던지면 해당 문서 `create_doc` 미호출, 예외 전파.
- 기존 문서 재-sync / 변경 없음 skip / (web) fetch-fail 경로에서는 `emit` 미호출.

### `tests/unit/test_connectors_api.py`
- `trigger_sync`가 `request.state.ingest_principal`을 `add_task` 인자로 캡처(미들웨어 없으면
  `None`).
- `_run_sync`에서 `_dispatch_sync`가 `HookAbort` 던짐 → `set_connector_sync_status(idle,
  last_error=...)` 호출되고 `set_connector_status(error)` **미호출**, 최종 status 불변.
- `_dispatch_sync(connector, principal=p)`가 각 커넥터 `.sync(..., principal=p)` 호출.

### `tests/unit/test_docs_upload_hooks.py` (신규)
- `upload_doc`: 등록된 콜백이 `HookAbort` → 응답 403, `create_doc`/`upload_object` 미호출.
- `upload_docs_batch`: 두 번째 파일에서 `HookAbort` → results에 파일1 성공, 파일2·파일3 error,
  루프 중단(파일3 `create_doc` 미호출).
- 콜백 미등록 시 두 엔드포인트 정상 동작(회귀 없음).

### 전체
- `.venv/bin/python -m pytest tests/ -q` 그린.
- `.venv/bin/ruff check src/ tests/` 클린 (라인 100자, E/F/I/UP).
