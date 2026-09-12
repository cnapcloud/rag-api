# US-07 — OpenTelemetry 트레이싱 (MCP → Langfuse)

## Goal

MCP 진입점에서 분산 트레이싱을 활성화해 Langfuse에서 전체 호출 흐름을 확인한다.

- **MCP tools**: `params._meta.traceparent`를 추출해 child span 생성.
  필드가 없으면 새 trace ID로 root span 자동 생성.
- **FastAPI REST API**: `FastAPIInstrumentor`로 HTTP 레벨 span 자동 생성.
  단, MCP 엔드포인트(`/mcp`)는 traceparent를 HTTP 헤더가 아닌 `_meta`로 전달하므로
  parent 연결이 불가한 noise span을 제거하기 위해 excluded_urls로 제외.

모든 span은 Langfuse OTLP 엔드포인트(Basic Auth)로 내보낸다.

## Acceptance Criteria

1. MCP tools/call에 `_meta.traceparent`가 있으면 AgentRun의 child span이 생성된다.
2. MCP tools/call에 `_meta`가 없어도 도구는 정상 동작하며 root span이 생성된다.
3. span 속성에 `mcp.tool.name`, `input.value`, `output.value`가 포함된다.
4. `output.value`는 문자열 200자, 리스트 3개로 슬림화해 valid JSON을 유지한다.
5. `tracing.enabled=false`이면 OTel 초기화가 발생하지 않는다.
6. `tracing.enabled=true`이면 로그에 `[trace_id:span_id]`가 찍힌다.
7. Langfuse UI에서 AgentRun trace 하위에 `mcp/tools/*` span이 보인다.

## Implementation

### 신규 파일

| 파일 | 역할 |
|------|------|
| `src/tracing/setup.py` | `init_tracing()` — TracerProvider + BatchSpanProcessor + Langfuse OTLP exporter 초기화. `OtelContextFilter` — 모든 LogRecord에 trace_id/span_id 주입. |
| `src/tracing/span.py` | `traced_tool` 데코레이터 — `_meta.traceparent` 자동 추출, input/output span 속성 설정. `tool_span` context manager. `_extract_traceparent` 헬퍼. |
| `tests/unit/test_tracing.py` | `_extract_traceparent` / `tool_span` 단위 테스트 14개 |

### 변경 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/api/app.py` | `_lifespan`에서 `init_tracing()` / `shutdown_tracing()` 호출. `FastAPIInstrumentor.instrument_app(excluded_urls="/mcp$")`. |
| `src/config/settings.py` | `TracingSettings` 모델 추가 (`enabled`, `langfuse_baseurl`, `langfuse_public_key`, `langfuse_secret_key`, `service_name`). |
| `src/main.py` | `_configure_logging()`에서 `tracing.enabled=true`이면 `[trace_id:span_id]` 포맷 + `OtelContextFilter` 적용. |
| `src/mcp_server/tools/search.py` | `@traced_tool` 데코레이터 적용, `trace.get_current_span()`으로 속성 설정. |
| `src/mcp_server/tools/docs.py` | 동일. |
| `src/mcp_server/tools/kb.py` | 동일. |
| `pyproject.toml` | `opentelemetry-api/sdk/exporter-otlp-proto-http/instrumentation-fastapi` 의존성 추가. |
| `settings.yaml` | `mcp.transport: streamable-http`, `tracing:` 섹션 추가. |

### 주요 설계 결정

- `POST /mcp` HTTP span은 Claude가 traceparent를 HTTP 헤더가 아닌 `_meta`(MCP 프로토콜 body)에 넣어 전달하므로 FastAPIInstrumentor가 부모를 알 수 없어 별도 root trace로 분리된다. `excluded_urls="/mcp$"`로 제거.
- output은 직렬화 전 `_slim()`으로 구조를 유지하면서 크기를 줄인다 (JSON 문자열을 직접 자르면 invalid JSON 발생).
- 리스트 truncation 시 `{"items": [...], "omitted": "N items not shown"}` 형태로 감싸 사실을 명시.

## Status: done
