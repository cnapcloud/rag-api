# RAG API

LlamaIndex + Dagster 기반 문서 인제스트 및 하이브리드 검색 파이프라인.

- API를 통한 문서 업로드 및 삭제, 자동 벡터 인덱스 반영
- 대용량 문서 배치 처리 및 병렬 임베딩 지원
- 파이프라인 단계별 분리 구조로 재처리 및 확장이 용이
- Ollama(로컬) / OpenAI 임베딩 모델 선택 지원

---

## 시작

### 1. 사전 요구사항

Ollama가 실행 중이어야 하며 `bge-m3` 모델이 설치되어 있어야 한다.

```bash
ollama pull bge-m3
```

### 2. 설정

`docker/settings.yaml`에서 Ollama 주소를 환경에 맞게 수정한다.

```yaml
embedding:
  ollama_url: "http://<ollama-host>:11434"
```

GPU 서버가 없어 Ollama를 직접 띄우기 어렵다면 OpenAI 임베딩으로 대체할 수 있다 (사전 요구사항의
`ollama pull` 단계는 건너뛰어도 된다). `provider.name`을 바꾸고 `embedding.model`/`vector_size`를
OpenAI 모델에 맞게 함께 수정해야 한다 — `vector_size`가 실제 임베딩 차원과 다르면 Qdrant 컬렉션
생성/검색이 깨진다.

```yaml
# settings.yaml
provider:
  name: "openai"

embedding:
  model: "text-embedding-3-small"
  vector_size: 1536              # text-embedding-3-small/ada-002 기준, bge-m3(ollama)는 1024
```

`OPENAI_API_KEY`는 `docker/settings.yaml`이 아니라 `docker/.env`에 넣는다 (env var 오버라이드로
`provider.openai_api_key`에 주입됨).

```bash
# docker/.env
OPENAI_API_KEY=sk-...
```

Knowledge Base 목록도 이 파일에서 정의한다. 앱 기동 시 자동으로 생성된다.

```yaml
knowledge_bases:
  - id: "kb-01"
    name: "지식베이스 01"
    description: "첫 번째 지식베이스"
```

`docker/.env`에서 MinIO / Redis 자격증명을 확인한다. 기본값은 개발용이며 프로덕션 배포 전에 변경한다.
MinIO는 `rag-api` 앱이 읽는 `S3_ACCESS_KEY`/`S3_SECRET_KEY`가 실제 변수명이고,
`docker-compose.yml`이 이 값을 MinIO 서버가 요구하는 `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`로
매핑한다(둘이 반드시 같은 값이어야 함).

```bash
S3_ACCESS_KEY=admin
S3_SECRET_KEY=password
REDIS_PASSWORD=redis
```

같은 파일의 `CONNECTOR_SECRET_KEY`(커넥터 인증정보 암호화 키)도 프로덕션 배포 전에 직접 생성한 값으로 교체한다. 미설정 시 소스코드에 공개된 기본 키로 조용히 폴백된다.

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Postgres 자격증명은 세 곳에 걸쳐 있어 함께 바꿔야 실제로 반영된다.

```yaml
# docker-compose.yml — postgresql 서비스 자체의 superuser 계정 (앱이 쓰는 계정과는 다름)
postgresql:
  environment:
    POSTGRES_PASSWORD: password   # 변경 필요

# docker/init-db.sql — 앱이 실제로 쓰는 rag-api 롤 비밀번호가 SQL 리터럴로 하드코딩되어 있음
CREATE USER "rag-api" WITH PASSWORD 'password';   # 변경 필요 (.env의 POSTGRES_PASSWORD와 동일한 값으로)

# docker/.env — settings.py가 이 환경변수로 postgres.password를 오버라이드함
POSTGRES_PASSWORD=password        # 변경 필요 (init-db.sql과 동일한 값으로)
```

`init-db.sql`은 Postgres 볼륨을 처음 초기화할 때만 실행되므로, 이미 기동한 적이 있는 환경이라면
`docker-compose down -v`로 `pg_data` 볼륨을 지우고 다시 올려야 새 비밀번호가 실제로 적용된다.

### 3. 서비스 시작

```bash
cd docker
docker compose up -d --build
```

`minio-init` 컨테이너가 스토리지 버킷을 초기화한다. 정상 종료 여부를 확인한다.

```bash
docker compose ps
# minio-init 상태가 Exited (0) 이어야 한다
```

---

## 문서 인덱싱

PDF, Word(docx/doc), 텍스트(txt), 마크다운(md), 한글(hwp), HTML, reStructuredText(rst), 이메일(eml),
CSV/TSV, JSON, EPUB, Excel(xlsx/xls), PowerPoint(pptx/ppt)와 주요 소스코드 확장자(py, ts, js, go, java 등)를
지원한다 (전체 목록은 [parser/extensions.py](src/rag_api/pipeline/steps/parser/extensions.py) 참고).

```bash
# 문서 업로드 — 응답에서 doc_id를 확인한다
curl -X POST http://localhost:8000/api/kb/kb-01/docs/upload \
  -F "file=@./data/sample.pdf"
# {"doc_id": "87131b1a-...", "source_uri": "sample.pdf", ...}

# 인덱싱 상태 확인 (업로드 응답의 doc_id 사용)
curl http://localhost:8000/api/kb/kb-01/docs/87131b1a-.../status

# KB 전체 문서 조회
curl http://localhost:8000/api/kb/kb-01/docs

# 문서 삭제 — 비동기 처리 (202), pending → deleting 순서로 진행됨
curl -X DELETE http://localhost:8000/api/kb/kb-01/docs/87131b1a-...
```

---

## 검색

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "오래된 참나무", "kb_ids": ["kb-01"]}'
```

---

## MCP 연결 (Streamable HTTP)

```bash
# 1단계 — 세션 초기화
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

---

## 모니터링

| 서비스 | 주소 | 용도 |
|---|---|---|
| RAG Admin | http://localhost:8080 | 문서 관리 및 검색 UI |
| MinIO Console | http://localhost:9001 | 업로드된 문서 파일 확인 |
| Qdrant Dashboard | http://localhost:6333/dashboard | 컬렉션 및 임베딩 벡터 현황 확인 |
| Dagster UI | http://localhost:3000 | 인제스트 파이프라인 실행 현황 (`queue_worker.enabled: false` 인 경우) |

---

## CI (GitHub Actions)

`.github/workflows/build-push.yml`은 ARC(actions-runner-controller)로 배포된 자체 호스팅 러너
(`runs-on: github-runner`)에서 실행되며, `docker buildx`는 사설 k8s 클러스터의 `infra` 네임스페이스
buildkit(`driver: kubernetes`)을 원격 빌더로 사용해 `linux/arm64,linux/amd64` 멀티아치 이미지를 빌드한다.

---

## 개발 참여

기능/버그 수정을 진행하려면 [SPEC-DRIVEN-AI-DEVELOPMENT.md](SPEC-DRIVEN-AI-DEVELOPMENT.md)의 스펙 기반 개발 절차
(요건 → 설계 → 작업 단위 → 구현 계획)를 따른다.
