# US-51: 파이프라인 훅 — 신규 문서 생성 직전 등록 기반 콜백

**상태**: done

> 설계: [pipeline-hooks.md](../../../docs/internal/design/pipeline-hooks.md)
> 구현 계획: [plans/51-pipeline-hooks-before-doc-create.md](../plans/51-pipeline-hooks-before-doc-create.md)

## 목적

문서 개수 상한 같은 정책은 rag-api가 아니라 vendoring 앱(rag-ent-api)이 소유하지만
([settings-composition.md] 원칙), 문서가 KB에 들어오는 경로는 커넥터 3종(web/confluence/
github)과 업로드 2종(단건/배치)으로 흩어져 있다. vendoring 앱이 각 경로를 오버라이드하는
대신, rag-api가 "새 문서 row가 만들어지기 직전"이라는 이벤트를 한 지점에서 발화하고 앱이
콜백을 붙일 수 있게 하는 등록 기반 훅을 둔다. 콜백이 예외를 던지면 그 문서의 유입만
중단하고, 아니면 그대로 진행한다.

## 범위

- `rag_api/hooks.py` 신규 모듈: 모듈 전역 레지스트리(`_registry`), `register()` /
  `unregister()` / `emit()`, 기저 예외 `HookAbort`, `@dataclass(frozen=True) BeforeDocCreate`
  (`kb_id` / `principal: Any` / `source_type: str | None`). 커넥터·라우터를 import 하지 않는다
  (역방향 의존만).
- 실행 계약 구현: 콜백은 `register()` 순서대로 실행, 콜백 예외는 `emit()` 밖으로 전파(이후
  콜백 미실행, `emit()`은 예외를 삼키지 않음), 동기 실행, 미등록 시 `emit()` 무연산, 재진입
  (콜백 안에서 `emit`/`register`/`unregister`) 미지원.
- 생산자 5경로에서 신규 문서 확정 직후(`get_doc_by_source()` → `None`) `create_doc()` 직전에
  `emit(BeforeDocCreate(...))`:
  - `connectors/web.py` `_process_page` (정상 스테이징 경로만 — fetch-fail로 `status="failed"`
    row를 만드는 분기 제외)
  - `connectors/confluence.py` `_process_page`, `_process_attachment`
  - `connectors/github.py` 파일 처리 메서드
  - `api/routers/docs.py` `upload_doc` (`existing is None` 분기)
  - `api/routers/docs.py` `upload_docs_batch` (루프 내 `existing is None` 분기)
- 기존 문서 재-sync / 변경 없음 skip / fetch 실패 에러 row 경로에서는 발화하지 않는다.
- `principal` 관통 배선:
  - HTTP 경로(`upload_doc`, `upload_docs_batch`): `getattr(request.state, "ingest_principal",
    None)`을 읽어 `BeforeDocCreate`에 실어 보낸다.
  - 커넥터 sync 경로: `POST /connectors/{id}/sync` 핸들러가 **스케줄 시점**에 `principal`을
    평범한 값으로 읽어 `background_tasks.add_task(_run_sync, ..., principal=...)`로 캡처하고,
    `_run_sync` → `_dispatch_sync` → `XConnector.sync(..., principal=...)` → `self._principal`
    → `emit`으로 관통시킨다 (`request.state`는 백그라운드 태스크로 넘어가지 않음).
- `HookAbort` 포획 지점 3곳:
  - `connectors/_run_sync`: `except HookAbort`를 `except Exception` **앞에** 추가. 훅에 의한
    중단은 `sync_status="idle"` + `last_error` 경고로만 남기고 커넥터를 `status="error"`로
    표시하지 않는다. 중단 이전에 이미 커밋된 문서는 유지.
  - `docs.upload_docs_batch`: `HookAbort`를 잡아 현재 항목 + 남은 항목 결과에 error 표시 후
    루프 `break`.
  - `docs.upload_doc`: 전파. `app.py` 예외 핸들러에 `HookAbort` → HTTP 403 매핑 추가.
- `docs/internal/design/http-error-codes.md`에 `HookAbort` → 403 매핑 반영.

## 비범위

- **커넥터 스테이징 통합 리팩터** — web/confluence/github의 중복 스테이징 시퀀스를 공통
  베이스로 추출하는 작업. `emit` 호출을 한 곳으로 모을 수 있으나 이 훅과 독립적이라 별도 US로
  넘긴다.
- **sync 라이프사이클 훅**(`BeforeConnectorSync` / `AfterConnectorSync`) — 발화 단위가 문서가
  아니라 sync 실행 1회. 레지스트리는 그대로 지원하므로 필요 시 이벤트 dataclass만 추가.
- **per-user / per-group 쿼터 로직** — 소비자(vendoring 앱) 몫. 이 US는 `principal` 배선까지만.
- **CLI(`rag-api ingest`) 게이팅** — CLI 프로세스는 아무 콜백도 등록하지 않아 자동 무연산.
- **rag-ent-api 쪽 소비자 구현**(`IngestQuotaError`, `_enforce_doc_quota`, OIDC 미들웨어에서
  `request.state.ingest_principal` 세팅) — 해당 저장소의 별도 백로그.

## 완료 기준

- [x] `emit()`이 `type(event)`에 등록된 콜백을 `register()` 순서대로 실행한다
      (`test_pipeline_hooks.py::TestEmit`)
- [x] 등록된 콜백이 없으면 `emit()`은 무연산으로 즉시 반환한다
- [x] 콜백이 던진 예외(`HookAbort`든 아니든)는 `emit()` 밖으로 전파되고 이후 콜백은 실행되지
      않는다
- [x] `hooks.py`가 `connectors/`·`api/`를 import 하지 않는다 (서브프로세스 import 그래프 검증)
- [x] 5개 생산자 경로가 신규 문서 확정 직후·`create_doc()` 직전에만 `emit(BeforeDocCreate)`
      하고, 재-sync / 변경 없음 skip / fetch-fail 에러 row 경로에서는 발화하지 않는다
      (`test_web_connector.py` / `test_confluence_connector.py` / `test_github_connector.py` /
      `test_docs_upload_hooks.py`)
- [x] HTTP 업로드 경로가 `request.state.ingest_principal`을 이벤트에 싣고, 미설정 시 `None`이
      전달된다
- [x] 커넥터 sync 경로가 요청 시점 `principal`을 캡처해 `emit`까지 관통시킨다 (rag-api 단독
      배포 시 `None`) — `test_connectors_api.py::TestTriggerSync::test_captures_ingest_principal_for_background_task`,
      `test_web_connector.py::TestDispatchSync::test_principal_is_threaded_through_to_connector_sync`
- [x] 등록된 콜백이 `HookAbort`를 던지면 커넥터 sync는 `sync_status="idle"` + `last_error`
      세팅으로 끝나고 `status`는 `"error"`가 되지 않으며, 중단 이전 커밋된 문서는 유지된다
      (`test_connectors_api.py::TestSyncHookAbort`)
- [x] `upload_docs_batch`에서 `HookAbort` 발생 시 현재 + 남은 파일이 응답에 error로 표시되고
      루프가 중단된다
- [x] `upload_doc`에서 `HookAbort`가 HTTP 403으로 매핑된다
- [x] 관련 테스트 전체 통과 (`pytest tests/` — 685 passed, 1 skipped)

## 의존성

- US-16 — Connector CRUD + Sync API. `POST /connectors/{id}/sync` → `_run_sync` →
  `_dispatch_sync` 경로가 있어야 `principal` 관통 배선을 얹을 수 있다. (완료됨)
- US-18 / US-20 / US-21 — web/confluence/github 커넥터의 스테이징 시퀀스가 `emit` 삽입 지점.
  (모두 완료됨)

## 오픈 이슈

- (해결) `HookAbort` 정의 위치 — `exceptions.py`에 두고(`RAGError` 미상속) `hooks.py`가 재노출.
  하드 룰("예외 클래스는 exceptions.py에만")과 설계의 공개 API를 모두 만족. `05-exception-handling.md`
  / `http-error-codes.md` / `pipeline-hooks.md` §3에 명시.
- (해결) `upload_docs_batch` 응답 형식 — 기존 거부 항목과 동일하게
  `{"title", "error": str(e), "status": "error"}`로 현재 + 남은 파일 전부 append 후 `break`.
- 첫 소비자인 rag-ent-api 쿼터 기능과의 릴리스 정합성 — rag-api가 `emit` 지점과 `principal`
  배선(이번 US)을 먼저 내보내야 rag-ent-api가 `register()`할 수 있다. 배포는 rag-api 선행.
  rag-ent-api 쪽 소비자 구현(`IngestQuotaError`, `_enforce_doc_quota`, OIDC 미들웨어의
  `request.state.ingest_principal` 세팅)은 해당 저장소 별도 백로그.
