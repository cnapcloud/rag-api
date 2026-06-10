# Plan 01 — MCP Server Implementation

**status**: done
**covers**: US-01

---

## Goal

RAG API 검색 기능을 MCP 툴로 노출하여 AI 어시스턴트(LibreChat, Claude Desktop 등)가
직접 KB를 조회할 수 있도록 한다.

---

## Architecture

- `mcp` Python SDK 사용 (`pip install mcp`).
- FastAPI 서버와 독립적으로 기동 — 기존 infra/rag 함수를 직접 호출 (HTTP 왕복 없음).
- 전송: stdio (기본, 로컬 어시스턴트) / sse (원격 배포).

```
src/mcp/
├── __init__.py
├── server.py          # FastMCP 인스턴스 + 툴 등록
└── tools/
    ├── __init__.py
    ├── search.py      # search 툴
    ├── kb.py          # list_knowledge_bases 툴
    └── docs.py        # get_document_status 툴
```

---

## Settings 확장

`src/config/settings.py`에 추가:

```python
class McpSettings(BaseModel):
    enabled: bool = True
    transport: str = "stdio"   # stdio | sse
    host: str = "0.0.0.0"
    port: int = 8001
```

`Settings`에 필드 추가: `mcp: McpSettings = Field(default_factory=McpSettings)`

`settings.yaml` 추가:
```yaml
mcp:
  enabled: true
  transport: stdio

# MCP search 동작에 영향하는 기존 설정값 (tool 스키마 미노출)
retrieval:
  top_k: 10       # search tool top_k 기본값
  alpha: 0.5      # dense/sparse 비율 (0=sparse only, 1=dense only)
```

---

## Tool 스펙

### `search`

```
입력:
  query   string        필수 — 자연어 질문
  kb_ids  list[string]  선택 — 미지정 시 전체 KB 검색
  top_k   int           선택 — 반환 청크 수 (기본값: settings.retrieval.top_k)

출력:
  results[]:
    text       string
    score      float
    kb_id      string
    doc_key    string
    page_num   int | null
    chunk_idx  int
  latency_ms  int
```

- kb_ids 미지정 → `get_settings().knowledge_bases`의 전체 id로 대체.
- top_k 미지정 → `settings.retrieval.top_k` 사용.
- alpha(dense/sparse 비율), rerank 여부는 `settings.yaml` 고정값 — tool 스키마 노출 안 함.
- 구현: `rag.retriever.hybrid_search()` + `rag.reranker.rerank_async()` 직접 호출.

---

### `list_knowledge_bases`

```
입력:  없음

출력:
  knowledge_bases[]:
    id           string
    description  string
```

- `get_settings().knowledge_bases` 읽기.

---

### `get_document_status`

```
입력:
  kb_id    string  필수
  doc_key  string  필수

출력:
  status      string  (pending | processing | indexed | error | not_found)
  indexed_at  string | null
  size_bytes  int | null
  etag        string | null
```

- `infra.redis.get_doc_meta(kb_id, doc_key)` 호출.

---

## CLI 진입점

`src/main.py`에 Typer 커맨드 추가:

```python
@app.command("serve-mcp")
def serve_mcp(
    transport: str = typer.Option(None, help="stdio | sse"),
    port: int = typer.Option(None, help="SSE port"),
):
    """Start the MCP server."""
```

---

## 구현 순서

1. `src/config/settings.py` — `McpSettings` 추가
2. `src/mcp/tools/kb.py` — `list_knowledge_bases`
3. `src/mcp/tools/docs.py` — `get_document_status`
4. `src/mcp/tools/search.py` — `search` (kb_ids 미지정 시 전체 KB 자동 확장)
5. `src/mcp/server.py` — FastMCP 인스턴스 + 툴 등록
6. `src/main.py` — `serve-mcp` 커맨드
7. `settings.example.yaml` — `mcp:` 섹션 추가
8. `tests/unit/test_mcp_tools.py` — mock_redis, mock_qdrant 픽스처 사용

---

## 테스트 전략

- 툴 함수 단위 테스트: `infra.redis`, `rag.retriever`를 conftest 픽스처로 Mock.
- 실제 인프라 연결 없음 (hard rule).
- kb_ids 미지정 시 전체 KB로 확장되는 경로 명시적 테스트.

---

## 범위 제외

- MCP Resources / Prompts — 추후 별도 US.
- MCP를 통한 문서 업로드 — REST 전용 유지.
- SSE 인증 — 리버스 프록시 레벨에서 처리.
