# US-07 — OpenTelemetry 트레이싱 (API + MCP → Langfuse)

## Goal

두 진입점에서 분산 트레이싱을 활성화한다.

- **FastAPI REST API**: 인바운드 `traceparent` HTTP 헤더를 추출해 child span 생성.
  헤더가 없으면 새 trace ID로 root span 자동 생성.
- **MCP**: `params._meta.traceparent`를 추출해 child span 생성.
  필드가 없으면 새 trace ID로 root span 자동 생성.

모든 스팬은 Langfuse OTLP 엔드포인트로 내보낸다.

## Acceptance Criteria

1. REST API 요청에 `traceparent` 헤더가 있으면 child span이 생성된다.
2. REST API 요청에 헤더가 없으면 root span(새 trace ID)이 자동 생성된다.
3. MCP tools/call에 `_meta.traceparent`가 있으면 child span이 생성된다.
4. MCP tools/call에 `_meta`가 없어도 도구는 정상 동작하며 root span이 생성된다.
5. 스팬 속성에 `mcp.tool.name` (MCP), HTTP method/route (API)가 포함된다.
6. `tracing.enabled=false`이면 OTel 초기화가 발생하지 않는다.
7. Langfuse UI에서 LibreChat trace 하위에 RAG API 스팬이 보인다.
