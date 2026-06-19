# API Guide

API 사용자 및 운영자를 위한 엔드포인트 사용 가이드.
스키마 및 내부 데이터 구조는 [api-spec.md](api-spec.md) 참고.

Base URL: `http://localhost:8000`

---

## 1. 상태 확인

```bash
# 서버 생존 여부
curl http://localhost:8000/health

# 인프라 헬스체크 (Qdrant / Redis / S3 / Ollama)
curl http://localhost:8000/ready
```

---

## 2. 지식베이스 (KB)

```bash
# 전체 KB 목록
curl http://localhost:8000/api/kb

# KB 생성
curl -X POST http://localhost:8000/api/kb \
  -H "Content-Type: application/json" \
  -d '{"kb_id": "kb-01", "description": "테스트 KB"}'

# KB 삭제 (Qdrant + S3 + Redis 모두 삭제)
curl -X DELETE http://localhost:8000/api/kb/kb-01
```

---

## 3. 문서 인덱싱

PDF, Word(docx), 텍스트(txt), 마크다운(md), 한글(hwp) 형식을 지원합니다.

```bash
# 단일 파일 업로드
curl -X POST http://localhost:8000/api/kb/kb-01/docs/upload \
  -F "file=@./data/doc.pdf"

# 복수 파일 업로드
curl -X POST http://localhost:8000/api/kb/kb-01/docs/upload/batch \
  -F "files=@./data/a.pdf" \
  -F "files=@./data/b.pdf"

# KB 전체 문서 목록
curl http://localhost:8000/api/kb/kb-01/docs

# 상태별 필터 (pending / running / indexed / failed)
curl "http://localhost:8000/api/kb/kb-01/docs?status=failed"

# 단일 문서 인덱싱 상태 확인
curl http://localhost:8000/api/kb/kb-01/docs/doc.pdf/status

# 문서 삭제 (벡터 + 메타데이터 + S3 파일)
curl -X DELETE http://localhost:8000/api/kb/kb-01/docs/doc.pdf

# 전체 KB 문서 현황 일괄 조회
curl http://localhost:8000/api/docs/status
```

---

## 4. 재인덱싱 / 복구

ETag가 동일하면 재인덱싱을 건너뜁니다. `force=true`로 강제 재처리합니다.

```bash
# KB 전체 재인덱싱 (변경된 파일만)
curl -X POST http://localhost:8000/api/kb/kb-01/reindex

# KB 전체 강제 재인덱싱
curl -X POST "http://localhost:8000/api/kb/kb-01/reindex?force=true"

# 단일 문서 재인덱싱
curl -X POST "http://localhost:8000/api/kb/kb-01/docs/reindex?key=doc.pdf"

# 단일 문서 강제 재인덱싱 (failed 상태 등)
curl -X POST "http://localhost:8000/api/kb/kb-01/docs/reindex?key=doc.pdf&force=true"

# stuck 문서 복구 — status=running 인 경우에만 사용
curl -X POST http://localhost:8000/api/kb/kb-01/docs/doc.pdf/recover
```

---

## 5. 검색

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "검색어",
    "kb_ids": ["kb-01", "kb-02"]
  }'
```

옵션을 지정할 경우:

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "검색어",
    "kb_ids": ["kb-01"],
    "options": {
      "mode": "hybrid",
      "top_k": 10,
      "hybrid": {
        "alpha": 0.5
      },
      "similarity": {
        "min_score": 0.7
      },
      "rerank": {
        "enabled": true,
        "top_n": 5
      }
    }
  }'
```

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `mode` | settings | `"hybrid"` (dense+sparse) 또는 `"similarity"` (dense-only). 생략 시 settings.retrieval.mode 사용 |
| `top_k` | settings | 반환할 최대 청크 수 |
| `hybrid.alpha` | settings | 1.0 = Dense 100%, 0.0 = Sparse(키워드) 100%. hybrid 모드에서만 적용 |
| `similarity.min_score` | settings | similarity 모드에서 반환할 최소 코사인 유사도 (0.0~1.0) |
| `rerank.enabled` | true | 리랭킹 활성화 여부 |
| `rerank.top_n` | settings | 리랭킹 후 반환할 결과 수 |

---

## 6. Knowledge Base 관리

### KB 목록 조회

```bash
curl http://localhost:8000/api/kb
```

응답:

```json
{
  "knowledge_bases": [
    {
      "kb_id": "kb-99",
      "kb_name": "지식베이스 99",
      "description": "첫 번째 지식베이스입니다.",
      "tags": []
    }
  ]
}
```

### KB 생성

```bash
curl -X POST http://localhost:8000/api/kb \
  -H "Content-Type: application/json" \
  -d '{
    "kb_id": "kb-99",
    "kb_name": "지식베이스 99",
    "description": "첫 번째 지식베이스입니다.",
    "tags": ["tag1", "tag2"]
  }'
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `kb_id` | 필수 | KB 식별자 (중복 불가) |
| `kb_name` | 선택 | 표시 이름 (기본값: `""`) |
| `description` | 선택 | 설명 |
| `tags` | 선택 | 태그 목록 (기본값: `[]`) |

응답 (HTTP 201):

```json
{ "kb_id": "kb-99", "status": "created" }
```

이미 존재하는 `kb_id`로 생성 시 HTTP 409 반환.

### KB 삭제

```bash
curl -X DELETE http://localhost:8000/api/kb/kb-99
```

Qdrant 컬렉션 → S3 오브젝트 → Postgres 메타데이터 순으로 삭제. 문서 메타데이터는 cascade 삭제.

응답 (HTTP 200):

```json
{ "kb_id": "kb-99", "status": "deleted", "s3_objects_deleted": 7 }
```

존재하지 않는 KB 삭제 시 HTTP 404 반환.

## 7. MCP 연결

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
