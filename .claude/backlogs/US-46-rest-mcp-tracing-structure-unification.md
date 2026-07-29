# US-46: REST/MCP 트레이싱 구조 통일 — root span + business span(input/output) 표준화

**상태**: in-progress

> 구현 상세: [plans/46-rest-mcp-tracing-structure-unification.md](../plans/46-rest-mcp-tracing-structure-unification.md)

## 목적

현재 REST(`/api/*`)는 `FastAPIInstrumentor` 자동 계측만 있어 HTTP 메타데이터는 있지만 input/output이
Langfuse에 안 남는다. MCP는 `traced_tool`로 input/output은 남지만 `/mcp$`가 `excluded_urls`로 빠져있어
HTTP 레벨 root span 자체가 없다. 같은 서비스인데 호출 경로(REST vs MCP)에 따라 Langfuse에 기록되는
정보의 완전성이 달라지는 게 문제.

## 범위

- HTTP 레벨 노이즈 서브스팬(`http receive`/`http send`)은 계측 대상에서 제외한다.
- ~~MCP streamable-http 호출도 REST와 동일하게 자동 root HTTP span 생성 대상에 포함시킨다.~~
  **되돌림(2026-07-25) — 아래 오픈 이슈 "MCP root span 재exclude" 참고.** `/mcp$`는 `excluded_urls`
  유지. stdio transport는 애초에 HTTP 레이어가 없으므로 이번 범위에서 고려하지 않는다.
- REST 라우터 핸들러(`search` / `kb` / `docs` / `connectors`)의 input/output을 트레이싱에 기록한다.
  MCP `mcp/tools/*`처럼 별도 자식 business span을 만드는 대신, FastAPIInstrumentor가 이미 생성한
  HTTP root span(라우트 경로 자체가 호출을 구분해줌) 하나에 직접 붙인다 — 설계 상세는 구현계획 참고.
- REST/MCP 모두 OpenInference 표준 `openinference.span.kind` attribute를 채워 Phoenix 등
  OpenInference 호환 뷰어에서 span 종류가 구분되게 한다 (REST=`CHAIN`, MCP tool=`TOOL`).

## 비범위

- MCP stdio transport — 고려 대상 아님 (streamable-http만).
- REST 응답 스키마를 MCP tool 응답 스키마에 맞춰 축소하는 것 — REST는 필드가 더 풍부한 게 정상이므로
  있는 그대로 기록한다. 두 스키마를 일치시키는 작업은 하지 않는다.
- 민감정보(비밀번호, 토큰, API 키 등) span attribute 마스킹/redaction 정책 — 필요해지면 별도 US로 분리.

## 완료 기준

- [ ] HTTP 레벨 노이즈 서브스팬(`http receive`/`http send`)이 Langfuse에 더 이상 기록되지 않는다 —
      구현 완료(`instrument_app(exclude_spans=["receive", "send"])`), Langfuse 육안 확인은 미완.
- [x] ~~MCP streamable-http 호출 시 HTTP 레벨 root span이 자동 생성되고...~~ **되돌림
      (2026-07-25) — 아래 "설계 변경" 참고.** `/mcp$`는 다시 `excluded_urls`에 포함. `mcp/tools/*`
      business span(`openinference.span.kind=TOOL`)만 계속 생성, US-07 때와 동일한 구조로 복귀.
- [ ] REST `/api/*` 호출(search / kb / docs / connectors 전체) 시 HTTP root span 자체에
      `input.value`/`output.value`/`openinference.span.kind=CHAIN`이 기록된다 — 구현 완료
      (`rest_span`이 자식 span 대신 `trace.get_current_span()`에 직접 부착, 33개 핸들러 전체 적용),
      Langfuse/Phoenix 육안 확인은 미완.
- [x] 관련 테스트 전체 통과 — `tests/unit/test_tracing.py`에 `rest_span`/`set_redacted_input`
      테스트 추가(속성 부착/redaction/스트리밍 스킵 구조 검증, 신규 span 생성 안 함 확인), 전체
      스위트 579 passed.

## 의존성

- US-07 — 이 US가 만든 트레이싱 기반(`tracing/setup.py`, `tracing/span.py`, `traced_tool`)을 확장하는
  후속 작업. US-07 완료 당시엔 `exclude_spans` 옵션을 안 쓰고 `excluded_urls="/mcp$"`로 노이즈를
  제거했는데, 이번 US에서 한때 그 방식을 대체했다가(MCP도 자동 root span 생성) 2026-07-25에 다시
  `excluded_urls="/mcp$"`로 복귀했다 — 위 "설계 변경(2026-07-25b)" 참고.

## 오픈 이슈

- 완료 기준 3개가 Langfuse/Phoenix 육안 확인 대기 중 — 사용자 환경에서 `/api/search`, `/mcp` 실호출
  후 구조 확인되면 체크박스만 갱신하고 `상태`를 `done`으로 전환.
- **설계 변경(2026-07-25b) — MCP root span 재exclude**: MCP streamable-http 호출을 실사용해보니
  `POST /mcp` 자동 root span이 traceparent 유무와 무관하게 거의 항상 고아(자식/attribute 없음)로
  남았다. 원인은 두 가지: (1) 클라이언트가 `ctx.meta.traceparent`(HTTP 헤더가 아닌 MCP body)를
  보내면 `tool_span`이 그 외부 trace를 부모로 잡아 로컬 `POST /mcp`와 완전히 분리된다. (2) 더 근본적
  으로, FastMCP streamable-http는 세션의 백그라운드 메시지 처리 루프를 `initialize` 시점에 한 번만
  띄우고 이후 모든 `tools/call`이 그때 캡처된(이미 종료된) OTel context를 계속 재사용한다 — 즉
  traceparent가 없어도 두 번째 이후 요청부터는 그 요청 자신의 `POST /mcp` span이 구조적으로 항상
  고아가 된다. `trace.get_current_span()`을 직접 mutate해서 로컬 span에 input/output을 붙이는
  방식도 시도했으나, 이미 종료된 span에 대한 `set_attribute`/`update_name`은 OTel SDK가 예외 없이
  조용히 no-op 처리해서 아무 정보도 안 남았다. 결론: `/mcp` 자동 root span은 이 아키텍처에서 유용한
  정보를 담을 수 없으므로, US-07 때 방식대로 `excluded_urls`에 `/mcp$`를 다시 포함시켜 아예 생성하지
  않기로 했다. `mcp/tools/*`(`traced_tool`/`tool_span`)는 변경 없이 계속 input/output을 기록하고,
  `ctx.meta.traceparent`가 있으면 그 외부 trace에 정상적으로 nest된다(LiteLLM 등 에이전트 트레이스
  통합 사례로 확인됨).
- **설계 변경(2026-07-25)**: 처음엔 REST에도 MCP처럼 자식 business span(`rest/{handler}`)을 만드는
  방향이었는데, 실제 Langfuse 트레이스를 보니 루트 span 이름(`POST /api/search` 등)이 이미 라우트
  경로로 호출을 구분해줘서 자식 span이 정보 중복만 될 뿐 이득이 없었다. 그래서 REST는 자식 span 없이
  `trace.get_current_span()`(FastAPIInstrumentor가 만든 root span 그 자체)에 직접
  `input.value`/`output.value`를 붙이는 방식으로 바꿨다 — MCP는 `/mcp` root span 이름이 제네릭해서
  어떤 tool이 호출됐는지 구분이 안 되므로 `mcp/tools/*` 자식 span을 그대로 유지한다. 구현 상세는
  plan 문서 참고.
- `connectors.py::create_connector`/`patch_connector`의 `config` 필드는 시크릿을 포함할 수 있어
  기존 `crypto.mask_config()`를 재사용해 span input 캡처 전 마스킹했다. 이는 비범위에 명시한
  "민감정보 마스킹 정책 신설"이 아니라, 이미 있는 마스킹 로직을 트레이싱 캡처에도 적용한 것뿐이다
  (새 정책 설계는 하지 않음).

(참고: aiops 레포 쪽 Langfuse 크리덴셜 배선 디버깅(`TRACING_LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`
환경변수 누락으로 OTLP export 401) 과정에서 이 US의 설계 논의가 나왔음.)
