# Plan 46: REST/MCP 트레이싱 구조 통일

**대상 US**: US-46
**상태**: in-progress

## 배경

`opentelemetry-instrumentation-asgi`의 `exclude_spans` 옵션으로 `http receive`/`http send`
서브스팬 노이즈를 제거하고, `excluded_urls`에서 `/mcp$`를 빼서 MCP streamable-http 호출도 REST와
동일하게 자동 root span 대상에 포함시킨다. REST 라우터 핸들러에는 MCP `traced_tool`과 대응되는
`rest_span` 데코레이터를 신설해 input/output을 business span에 채운다.

## 설계 메모 — kwargs 캡처로 일반화

`search.py`의 `SearchRequest`/`SearchResponse`처럼 단일 Pydantic 요청/응답 모델을 쓰는 핸들러는
`kb.py`/`docs.py`/`connectors.py`에는 드물다. 대부분 응답이 plain dict이고, GET 계열은 요청 body 자체가
없다(path/query 파라미터만). 그래서 "요청/응답 모델 `model_dump()`" 대신 `traced_tool`과 동일하게
**핸들러 kwargs 전체를 캡처**하는 방식으로 일반화한다:

- input: 핸들러에 전달된 모든 kwargs(path/query 파라미터 + Pydantic body가 있으면 그것도 포함).
  직렬화 불가능한 타입(`BackgroundTasks`, `UploadFile`, `File(...)`로 받은 바이너리)은 제외.
  Pydantic 모델 kwarg는 `model_dump()` 후 slim.
- output: 리턴값이 Pydantic 모델이면 `model_dump()`, dict/list면 그대로 slim. `StreamingResponse`
  등 body가 스트림인 경우 캡처를 생략하고 `output.skipped="streaming_response"` attribute만 남긴다.
- `connectors.py`의 `config` 필드는 시크릿을 포함할 수 있으므로, `create_connector`/`patch_connector`
  캡처 시 `crypto.mask_config()`를 거친 값만 span에 남긴다.

## 설계 메모 — REST는 자식 span이 아니라 root span에 직접 부착 (2026-07-25 변경)

최초 설계는 REST도 MCP `traced_tool`처럼 `rest/{handler_name}`이라는 별도 자식 span을 만드는
것이었다. 구현 후 실제 Langfuse 트레이스로 확인해보니:

- FastAPIInstrumentor는 request당 HTTP server span을 **하나만** 생성한다
  (`opentelemetry-instrumentation-asgi`의 `OpenTelemetryMiddleware.__call__`, 소스 확인 완료).
  Langfuse UI에 보이는 "트레이스 헤더 행 + 그 아래 span 행"은 같은 span을 두 번 보여주는 UI
  레이아웃일 뿐, 실제로 root span이 2개 있는 게 아니다.
- 그 root span의 이름 자체가 이미 `POST /api/search`처럼 라우트 경로로 호출을 구분해주므로,
  `rest/search`라는 자식 span은 정보를 중복시킬 뿐 실익이 없었다 (MCP는 다르다 — `/mcp` root span
  이름이 제네릭해서 어떤 tool이 호출됐는지 이름만으로 알 수 없으므로 `mcp/tools/{tool_name}` 자식
  span이 반드시 필요).

그래서 `rest_span`은 새 span을 만들지 않고, 핸들러 실행 시점에 이미 활성 상태인
`trace.get_current_span()`(= FastAPIInstrumentor가 만든 그 root span)에 직접
`input.value`/`output.value`를 얹는 방식으로 변경했다. 부수 효과: 예외 발생 시 에러 기록이 그
root span 한 곳에만 남는다(이전엔 자식 span과 root span 양쪽에 중복 기록될 뻔했다).

## 설계 메모 — `openinference.span.kind` 추가 (2026-07-25)

Phoenix(OpenInference 기반 뷰어) 호환을 위해 OpenInference 표준 attribute
`openinference.span.kind`를 채운다. 별도 패키지 의존성 추가 없이 표준 enum 값과 동일한 대문자
문자열만 `set_attribute`로 넣는다:

- REST(`rest_span`) → `"CHAIN"` — 라우트 전체가 여러 단계(조회/검증/변경 등)를 묶는 orchestration
  span이라는 의미. 모든 REST 핸들러에 동일하게 적용(CRUD든 search든 구분하지 않음 — 세분화하려면
  `RETRIEVER`/`RERANKER`처럼 `rag/retriever.py`/reranker 내부에 별도 span이 필요한데 이번 범위 밖).
- MCP(`tool_span`) → `"TOOL"` — MCP 프로토콜의 tool 호출이라는 의미와 정확히 대응.

## 구현 단계

1. **`src/rag_api/api/app.py::_instrument_tracing()`**
   - `FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/ready,/status$", exclude_spans=["receive", "send"])`
     — `excluded_urls`에서 `/mcp$` 제거, `exclude_spans` 추가.
   - 로그 메시지를 실제 동작에 맞게 갱신.

2. **`src/rag_api/tracing/span.py` 리팩터 + 신규 `rest_span`**
   - `traced_tool` 내부 nested closure(`_slim`/`_to_json`)를 모듈 레벨 함수로 승격 — `rest_span`과
     공유.
   - `rest_span` 데코레이터 추가: 새 span을 만들지 않고 `trace.get_current_span()`(FastAPIInstrumentor
     root span)에 `openinference.span.kind="CHAIN"` + 위 "설계 메모"의 kwargs 캡처 규칙으로
     input.value/output.value를 직접 부착.
   - `tool_span`에 `openinference.span.kind="TOOL"` attribute 추가(기존 자식 span 구조는 유지).

3. **라우터 적용**
   - `src/rag_api/api/routers/search.py::search` 우선 적용.
   - `kb.py` / `docs.py` / `connectors.py`의 나머지 핸들러에 동일 데코레이터 적용.
     - `docs.py::download_doc`은 output 캡처 생략(스트리밍).
     - `connectors.py::create_connector`/`patch_connector`는 `mask_config()` 적용 값만 캡처.

4. **테스트**
   - `tests/unit/test_tracing.py`에 `rest_span` 단위 테스트 추가 (`tool_span` 테스트 패턴 미러링):
     span 이름, input/output attribute, 비직렬화 kwarg 스킵, 스트리밍 응답 스킵.
   - 기존 MCP 관련 테스트(`_extract_traceparent`, `tool_span`) 회귀 확인.
   - 필요 시 in-memory exporter 기반으로 root+child nesting 스모크 테스트 추가(실제 인프라 연결 없이).

5. **수동 검증 (자동화 불가, 범위 밖)**
   - Langfuse/Phoenix 등 실제 뷰어에서 `/api/search`, `/mcp` 실호출로 trace 구조(자식 span 없이
     root span에 input/output이 바로 붙는지, `openinference.span.kind`가 CHAIN/TOOL로 보이는지)
     육안 확인은 사용자 환경에서 별도 진행.

## 완료 기준 매핑

- app.py 변경 → US-46 완료기준 1, 2
- rest_span + 라우터 적용 → US-46 완료기준 3
- 테스트 → US-46 완료기준 4
