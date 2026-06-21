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

### KB 수정

`name`, `description`, `tags` 중 전달한 필드만 업데이트합니다 (PATCH 의미론).

```bash
curl -X PATCH http://localhost:8000/api/kb/kb-99 \
  -H "Content-Type: application/json" \
  -d '{
    "kb_name": "새 이름",
    "description": "수정된 설명",
    "tags": ["tag1", "tag3"]
  }'
```

| 필드 | 필수 | 설명 |
|------|------|------|
| `kb_name` | 선택 | 표시 이름 |
| `description` | 선택 | 설명 |
| `tags` | 선택 | 태그 목록 (전체 교체) |

응답 (HTTP 200):

```json
{ "kb_id": "kb-99", "status": "updated" }
```

존재하지 않는 KB 수정 시 HTTP 404 반환.

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

# KB 전체 문서 목록 (기본: 1페이지, 20개, updated_at 내림차순)
curl http://localhost:8000/api/kb/kb-01/docs

# 페이지네이션
curl "http://localhost:8000/api/kb/kb-01/docs?page=2&page_size=50"

# 상태 필터 (running / indexed / failed / deleting)
curl "http://localhost:8000/api/kb/kb-01/docs?status=failed"

# doc_source 부분 문자열 검색 (대소문자 무시)
curl "http://localhost:8000/api/kb/kb-01/docs?search=report"

# 정렬 (sort_by: updated_at | created_at | doc_source | chunk_count | file_size)
curl "http://localhost:8000/api/kb/kb-01/docs?sort_by=doc_source&sort_order=asc"

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
curl -X POST "http://localhost:8000/api/kb/kb-01/docs/reindex?source=doc.pdf"

# 단일 문서 강제 재인덱싱 (failed 상태 등)
curl -X POST "http://localhost:8000/api/kb/kb-01/docs/reindex?source=doc.pdf&force=true"

# stuck 문서 복구 — status=running 인 경우에만 사용
curl -X POST "http://localhost:8000/api/kb/kb-01/docs/recover?source=doc.pdf"
```

---

## 5. 문서 목록 조회

`GET /api/kb/{kb_id}/docs`

### 쿼리 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `page` | int | 1 | 페이지 번호 (1-based) |
| `page_size` | int | 20 | 페이지당 항목 수 (최대 100, 초과 시 자동 클램핑) |
| `status` | str | — | 상태 필터: `running`, `indexed`, `failed`, `deleting` |
| `search` | str | — | `doc_source` 부분 문자열 검색 (대소문자 무시) |
| `sort_by` | str | `updated_at` | 정렬 기준: `updated_at`, `created_at`, `doc_source`, `chunk_count`, `file_size` |
| `sort_order` | str | `desc` | 정렬 방향: `asc`, `desc` |

- `total`은 필터 적용 후 전체 건수 (전체 문서 수가 아님).
- 범위를 벗어난 `page`는 `items: []`를 반환 (404 아님).
- `chunk_count`, `file_size` 정렬 시 NULL 값은 방향에 관계없이 항상 마지막.

### 요청 예시

```bash
# 2페이지, 상태=indexed, "report" 검색, doc_source 오름차순
curl "http://192.168.0.181:8000/api/kb/kb-01/docs?page=2&page_size=10&status=indexed&search=report&sort_by=doc_source&sort_order=asc"
```

### 응답 예시

```json
{
  "items": [
    {
      "doc_source": "reports/2024/report.pdf",
      "status": "indexed",
      "doc_type": "pdf",
      "chunk_count": 42,
      "file_size": 1258291,
      "embedding_model": "ollama/nomic-embed-text",
      "error": null,
      "created_at": "2026-06-19T14:30:00+00:00",
      "updated_at": "2026-06-19T14:32:00+00:00"
    }
  ],
  "total": 87,
  "page": 1,
  "page_size": 20
}
```

---

## 6. 검색

### hybrid 모드 (기본)

dense(의미) + sparse(키워드) 검색을 결합해 RRF로 재순위를 매깁니다.

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "검색어",
    "kb_ids": ["kb-01", "kb-02"],
    "options": {
      "mode": "hybrid",
      "top_k": 10,
      "hybrid": {
        "alpha": 0.5
      },
      "rerank": {
        "enabled": true,
        "top_n": 5
      }
    }
  }'
```

### similarity 모드

dense 벡터 코사인 유사도만 사용합니다. `min_score`로 낮은 유사도 결과를 걸러낼 수 있습니다.

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "검색어",
    "kb_ids": ["kb-01", "kb-02"],
    "options": {
      "mode": "similarity",
      "top_k": 10,
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

### 옵션 파라미터

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `mode` | settings | `"hybrid"` 또는 `"similarity"`. 생략 시 settings.retrieval.mode 사용 |
| `top_k` | settings | 최종 반환할 최대 청크 수 |
| `hybrid.alpha` | settings | 1.0 = Dense 100%, 0.0 = Sparse(키워드) 100%. hybrid 모드에서만 적용 |
| `similarity.min_score` | settings | 반환할 최소 코사인 유사도 (0.0~1.0). similarity 모드에서만 적용 |
| `rerank.enabled` | true | 리랭킹 활성화 여부 |
| `rerank.top_n` | settings | 리랭킹 후 반환할 결과 수 |

### 모드별 점수(score) 및 복수 KB 집계 방식

**hybrid 모드**

- 각 KB에서 `top_k`개를 독립적으로 검색 (dense 순위 + sparse 순위 합산 → KB 내 RRF 점수)
- 복수 KB 결과를 하나로 모아 RRF를 다시 적용해 순위를 재산출
- `score = 1 / (60 + rank)` — 1위 ≈ 0.0164, 10위 ≈ 0.0143
- 점수 절댓값은 의미 없음. 품질 제어는 `top_k`로 한다 (`min_score` 적용 불가)
- 최종 결과: 전체 candidate 중 RRF 점수 상위 `top_k`개 반환

**similarity 모드**

- 각 KB에서 `top_k`개를 독립적으로 검색 (코사인 유사도 기준)
- `min_score` 미만 결과를 KB별로 먼저 제거
- 복수 KB 결과를 합산한 뒤 코사인 유사도 내림차순으로 정렬
- 최종 결과: 정렬된 전체 candidate 중 상위 `top_k`개 반환

---

## 7. MCP 연결

VS Code `.vscode/mcp.json` (워크스페이스 기준):

```json
{
  "servers": {
    "rag-api": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

또는 사용자 전역 설정 (`settings.json`):

```json
{
  "mcp.servers": {
    "rag-api": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```
