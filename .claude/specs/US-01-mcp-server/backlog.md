# US-01 — MCP 서버

**status**: done

---

## 기능 요건

1. `search` 툴: query(필수), kb_ids(선택), top_k(선택) 입력 → 관련 청크 반환. kb_ids 미지정 시 전체 KB 검색.
2. `list_knowledge_bases` 툴: 인수 없음 → 등록된 KB 목록(id, 설명) 반환.
3. `get_document_status` 툴: kb_id + doc_key 입력 → 인덱싱 상태 및 메타데이터 반환.
4. `python -m main serve-mcp` 커맨드로 MCP 서버 기동.
5. 전송 방식은 stdio(기본) / sse 선택 가능, settings.yaml로 설정.
6. dense/sparse 비율(alpha), rerank 여부는 settings.yaml 고정값 — AI가 제어하지 않음.
