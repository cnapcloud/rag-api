# CNAP RAG API

LlamaIndex + Dagster 기반 문서 인제스트 및 하이브리드 검색 파이프라인.

- 문서 신규 / 변경 / 삭제를 자동 감지하여 벡터 인덱스에 반영
- 대용량 문서 배치 처리 및 병렬 임베딩 지원
- 파이프라인 단계별 분리 구조로 재처리 및 확장이 용이
- Ollama(로컬) / OpenAI 임베딩 모델 선택 지원

---

## 시작

Ollama가 실행 중이어야 하며 `bge-m3` 모델이 설치되어 있어야 한다.

```bash
# bge-m3 모델 설치 (최초 1회)
ollama pull bge-m3
```

`settings.yaml`에서 Ollama 주소를 환경에 맞게 수정한다.

```yaml
embedding:
  ollama_url: "http://<ollama-host>:11434"
```

```bash
cd docker
docker-compose up -d
```

---

## 문서 인덱싱

PDF, Word(docx), 텍스트(txt), 마크다운(md), 한글(hwp) 형식을 지원합니다.


```bash
# KB 생성
curl -X POST http://localhost:8000/api/kb \
  -H "Content-Type: application/json" \
  -d '{"kb_id": "kb-01", "description": "테스트 KB"}'

# 문서 업로드
curl -X POST http://localhost:8000/api/kb/kb-01/docs/upload \
  -F "file=@./data/ATD00002_2605.pdf"

# 인덱싱 상태 확인
curl http://localhost:8000/api/kb/kb-01/docs/ATD00002_2605.pdf/status

# 문서 삭제
curl -X DELETE http://localhost:8000/api/kb/kb-01/docs/ATD00002_2605.pdf

# KB 전체 문서 조회
curl http://localhost:8000/api/kb/kb-01/docs
```

---

## 검색

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "삼성증권", "kb_ids": ["kb-01"]}'
```

---

## MCP 연결 (Streamable HTTP)

```bash
# 1단계 — 세션 초기화 (mcp-session-id 헤더 값 확인)
SESSION=$(curl -sD - -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "test", "version": "1.0"}
    }
  }' | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')

# 2단계 — search 툴 호출
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "search",
      "arguments": {"query": "삼성증권", "kb_ids": ["kb-01"]}
    }
  }'
```

Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "rag-api": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## 모니터링

| 서비스 | 주소 | 용도 |
|--------|------|------|
| MinIO Console | http://localhost:9001 | 업로드된 문서 파일 확인 |
| Qdrant Dashboard | http://localhost:6333/dashboard | 컬렉션 및 임베딩 벡터 현황 확인 |
| Dagster UI | http://localhost:3000 | 인제스트 파이프라인 실행 현황 및 임베딩 진행 상태 확인 |