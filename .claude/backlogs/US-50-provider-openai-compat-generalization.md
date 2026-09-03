# US-50: 임베딩 provider 일반화 — 프로토콜 기반 접속 + OpenAI 호환 폴백

**상태**: done

> 설계: [settings-composition.md](../../docs/internal/design/settings-composition.md) §7 (provider 일반화)

## 목적

현재 임베딩 provider는 `ollama` / `openai` 두 값만 인식하고 각 벤더 전용 설정 필드를 직접
읽어, 새 임베딩 백엔드를 붙일 때마다 전용 분기와 전용 필드를 추가해야 한다. 같은 분기 로직이
rag-ent-api 캡셔닝에도 복제돼 있어 필드 하나를 바꾸면 두 저장소를 함께 고쳐야 한다. provider를
"접속 프로토콜 + 주소 + 인증"으로 재정의하고, 모르는 벤더는 OpenAI 호환 클라이언트로 폴백해
새 호스팅 벤더 추가가 `settings.yaml` 수정만으로 끝나게 한다.

## 범위

### 공통: provider 설정 모델

- `ProviderSettings`를 `name` / `url` / `api_key` 세 필드로 재정의한다. 벤더 전용 필드
  (`ollama_url`, `openai_api_key`)는 제거한다.
- `name`은 자유 문자열이다. 미지 값을 허용하며, 미지 값은 에러가 아니라 OpenAI 호환 경로로
  처리된다.
- 세 필드 모두 기본값이 있어 `provider` 블록을 통째로 생략할 수 있고, 생략 시 현재
  compose(Ollama) 동작과 완전히 동일해야 한다.
- `url`이 빈 값이면 "그 provider의 기본 엔드포인트"를 의미한다. 해석은 provider별로 다르다
  (아래 각 절).
- **`resolve_provider_conn()` 공개 헬퍼를 신설한다.** `provider` 설정을 받아 접속 정보
  `ProviderConn(base_url, api_key)`를 돌려주는 함수로, provider 필드명(`name` / `url` /
  `api_key`)을 아는 코드베이스 내 유일한 지점이다. 임베딩 팩토리 · `/ready` · rag-ent-api 캡셔닝이
  모두 이 헬퍼만 거쳐 provider에 접근한다.
  - `ollama` → `base_url`은 `url`(빈 값이면 `http://ollama:11434`), `api_key`는 없음.
  - 그 외 (`openai` / 미지 / jina) → `base_url`은 `url`(빈 값이면 `None` = 각 클라이언트 기본
    엔드포인트), `api_key`는 `provider.api_key`.
  - `resolve_provider_conn`과 반환 타입 `ProviderConn`을 `rag_api` 공개 import 경로로 노출해
    rag-ent-api E-31이 그대로 재사용한다 — provider 필드명을 아는 지점이 두 저장소 통틀어 한 곳.
- `OPENAI_API_KEY` 환경변수는 `provider.api_key`로 주입한다.

### Provider 1: Ollama (네이티브, 기본값)

- `name`이 비었거나 `ollama`이면 Ollama 네이티브 임베딩을 쓴다.
- `url`이 비면 `http://ollama:11434`로 폴백한다 (현재 기본값 유지 → 제로 config compose 보존).
- 다른 호스트의 Ollama를 쓰려면 `url`만 지정한다. 인증은 없다.

### Provider 2: OpenAI (본가)

- `name`이 `openai`이면 OpenAI 임베딩 API를 쓴다.
- `url`이 비면 OpenAI 기본 엔드포인트(`api.openai.com/v1`)를 쓴다.
- `api_key`(또는 `OPENAI_API_KEY` env)가 필요하다.
- 모델명은 OpenAI 모델 enum 검증을 우회해 전달한다 → 최신/미등록 모델명도 그대로 통과.

### Provider 3: OpenAI 호환 (미지 name 폴백)

- `name`이 `ollama` / `openai` / `jina` 중 어느 것도 아니면 이 경로로 처리한다 (vLLM,
  Text Embeddings Inference, Gemini의 OpenAI 호환 레이어 등).
- OpenAI SDK와 동일한 클라이언트를 쓰되 `url`을 필수로 요구한다 (커스텀 주소이므로). `url`은
  `/v1`을 포함한 완전한 base URL이어야 한다.
- 이 경로로 들어오면 "provider를 인식하지 못해 OpenAI 호환 클라이언트로 처리한다"는 로그를
  한 줄 남긴다. 에러는 아니다.
- `api_key`는 선택이다. 인증 없는 자체 호스팅 서버라도 SDK가 빈 키를 거부하므로, 비어 있으면
  무해한 placeholder를 자동 주입한다 (서버는 무시).
- query/passage 비대칭이 있는 모델(Gemini `gemini-embedding-001` 등)을 이 경로로 붙이면
  비대칭은 적용되지 않는다. 비대칭이 필요하면 네이티브 분기(별도 US)로 붙인다.

### Provider 4: Jina (네이티브)

- `name`이 `jina`이면 Jina 네이티브 임베딩을 쓴다 (`llama-index-embeddings-jinaai` 의존성
  추가).
- `url`이 비면 패키지 기본 엔드포인트를 쓴다. `api_key`가 필요하다.
- 인제스트(passage)와 검색(query) 호출에 서로 다른 task 값이 자동 전송돼, query/passage
  비대칭이 코드 개입 없이 처리된다. 이것이 Jina를 OpenAI 호환 경로가 아니라 네이티브로 두는
  이유다.

### 연동 지점 갱신

- `/ready` 헬스체크의 provider 분기를 `resolve_provider_conn()` 기준으로 바꾼다.
- 배포 기본 설정과 예시 설정 파일의 `provider` 블록을 새 형태로 바꾼다.
- KB 단위 설정 오버라이드에서 `provider.*` 거부 동작은 그대로 유지한다 (필드명만 갱신).
- 미지 provider를 에러로 취급하던 기존 동작을 제거한다.
- 설계 문서(`settings-composition.md`)에 provider 일반화 절을 추가한다: `url` 이원화(Ollama는
  bare host, OpenAI 호환은 `/v1` 포함), 미지 `name` → OpenAI 호환 폴백 규칙, 모델명 enum
  우회의 근거와 위험.

## 비범위

- **Gemini / Voyage 등 비대칭 벤더 네이티브 분기** — OpenAI 호환 경로로 붙기는 하나 task
  비대칭은 손실된다. 실제 채택 대상이 되면 각각 별도 US로 네이티브 분기 추가.
- **`params` / `document_params` / `query_params` 설정 passthrough** — 논의 후 폐기
  (2026-09-01). 벤더 고유 파라미터는 네이티브 분기가 캡슐화한다.
- **임베딩 모델 불일치 가드** — 색인에 쓴 모델과 검색에 쓰는 모델이 다르면 차단하는 기능.
  차원이 우연히 같으면(bge-m3 1024 ↔ jina-v3 1024) 런타임 에러 없이 검색 품질만 조용히
  붕괴하므로 위험도가 높다. 후속 US로 우선 배정 권장.
- **리랭커**(`retrieval.rerank.*`) — 독립 계층이라 손대지 않는다.
- **rag-ent-api 추종 변경**(캡셔닝 클라이언트의 헬퍼 전환, 자체 `settings.yaml` 갱신) —
  E-31에서 처리. 단 배포는 이 US와 동시 릴리스.

## 완료 기준

- [x] `ProviderSettings`가 `name` / `url` / `api_key` 세 필드만 가지며, 코드베이스에
      `ollama_url` / `openai_api_key` 참조가 남아 있지 않다.
- [x] `provider` 블록을 생략한 설정으로 로드하면 Ollama로 동작하고 `http://ollama:11434`에
      접속한다 (회귀 없음).
- [x] `provider.url`만 지정하면 그 호스트의 Ollama로 접속한다.
- [x] `name: openai` + `api_key`로 OpenAI 임베딩 클라이언트가 기본 엔드포인트로 생성된다.
- [x] `OPENAI_API_KEY` 환경변수가 `provider.api_key`로 주입된다.
- [x] 미지 `name`(예: `vllm`) + `url`이면 OpenAI 호환 클라이언트가 생성되고, "인식하지 못함"
      로그가 한 줄 남고, 에러가 발생하지 않는다.
- [x] 미지 `name` + `url`인데 `api_key`가 없어도 클라이언트 생성에 성공한다 (placeholder 자동
      주입).
- [x] `name: jina` + `api_key`로 Jina 네이티브 임베딩이 생성되고, 인제스트 호출과 검색 호출이
      서로 다른 task 값으로 나간다 (mock으로 요청 인자 검증).
- [x] `resolve_provider_conn()`이 `ollama`에 대해 `api_key` 없는 `ProviderConn`을, 그 외에 대해
      `provider.api_key`를 담은 `ProviderConn`을 돌려주고, `url`이 비면 `ollama`는
      `http://ollama:11434` / 그 외는 `base_url=None`으로 해석한다 (단위 테스트).
- [x] `resolve_provider_conn`과 `ProviderConn`이 `rag_api` 공개 경로에서 import된다 (rag-ent-api
      E-31이 쓸 수 있게).
- [x] KB 단위 설정에서 `provider.*` 오버라이드 저장이 여전히 거부된다.
- [x] `/ready`가 Ollama / OpenAI 호환 각 구성에서 정상 응답한다.
- [x] 관련 테스트 전체 통과 + ruff 통과. (US-50 무관 기존 실패 1건:
      `test_dedup_simhash.py::test_simhash_near_duplicate_low_hamming` — commit 1373b6e 이후
      브랜치에 이미 존재, 본 작업과 무관)

## 구현 메모

- 미지/`openai` provider 모두 `llama-index-embeddings-openai-like`의 `OpenAILikeEmbedding` 사용
  (모델명 enum 우회). `openai`는 `api_base`를 `https://api.openai.com/v1`로 채우는 것만 차이.
- Jina: `llama-index-embeddings-jinaai`가 방향과 무관하게 단일 `task`를 보내므로,
  `pipeline/steps/embed.py`에서 `_get_query_embedding`/`_get_text_embeddings`를 오버라이드해
  `retrieval.query` / `retrieval.passage`를 강제하는 얇은 서브클래스로 처리.
- `/ready`: ollama / openai만 전용 probe. jina / OpenAI 호환은 통일된 readiness 엔드포인트가
  없어 인프라 deps만 보고 200.
- 설계: `docs/internal/design/settings-composition.md` §7 (provider 일반화).

## 의존성

- 선행 US 없음.
- **배포는 rag-ent-api E-31과 동시 릴리스**. 이 US만 먼저 머지되면, 상속된 rag-ent-api
  Settings가 구 `ollama_url` / `openai_api_key` 키를 조용히 버리고 `url` / `api_key`가 빈 값이
  되어, rag-ent-api의 Ollama 임베딩·캡셔닝이 잘못된 호스트로 조용히 깨진다.

## 오픈 이슈

- **`url` 이원화 자동 보정** — 결정(2026-09-02): 자동 보정하지 않는다. OpenAI 호환 경로의
  `url`은 `/v1`을 포함한 완전한 base URL이어야 하며, 이를 문서(`settings-composition.md`
  provider 절 + settings.yaml 주석)로만 고정한다. root-mount 서버(`/embeddings` 직접 노출)에서
  자동 `/v1` append가 오히려 깨지기 때문.
- **미지 `name` 폴백의 디버깅성** — 결정(2026-09-02): `WARNING`. `ollamaa` 오타가 OpenAI 호환
  경로로 새어 404가 나는 상황을 로그에서 바로 알아채게 한다(logging convention상 fallback 발생 =
  WARNING).
- **모델명 enum 우회 + 차원 지정** — 결정(2026-09-02): 임베딩 클라이언트에 `dimensions`를
  전달하지 않는다. `embedding.vector_size`는 Qdrant 컬렉션 크기 지정 전용으로만 유지하고, 모델이
  반환하는 네이티브 차원을 그대로 쓴다(운영자가 둘을 일치시킬 책임). enum 우회는 `model` 인자
  검증만 우회하는 것으로 한정 — `llama-index-embeddings-openai-like`의 `OpenAILikeEmbedding`
  사용.
- **임베딩 모델 불일치 가드(비범위 항목)** — 설정만 바꾸고 재인제스트를 안 하면 차원이 우연히
  같을 때 검색 품질이 조용히 붕괴한다. 위험도 높음, 후속 US 우선 배정 권장.
