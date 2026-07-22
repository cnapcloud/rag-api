# LightRAG / GraphRAG 조사 노트

| 항목 | 내용 |
|------|------|
| 작성일 | 2026-07-22 |
| 배경 | rag-product 경쟁분석([03-competitive-analysis.md](../../../../rag-product/assessment/03-competitive-analysis.md))에 LightRAG를 추가 비교하는 과정에서, 본 제품의 딥 문서 이해 평가 오류를 발견하고 GraphRAG 도입 가능성까지 조사가 확장됨. 이 문서는 그 조사 내용을 정리한다 — competitive-analysis.md 자체는 수정하지 않음(별도 확인 필요). |
| 범위 | (1) 본 제품 딥 문서 이해 현황 정정, (2) MinerU vs RapidOCR/RapidLayout 비교, (3) LightRAG 아키텍처, (4) LightRAG 그래프 처리 방식과 "빠르다"의 실제 근거, (5) 본 제품에 도입한다면 필요한 작업과 리스크 |

---

## 1. 본 제품 딥 문서 이해 현황 정정

경쟁분석 문서(3.2절)는 본 제품(rag-api)의 "딥 문서 이해(OCR·표·레이아웃)"를 X(미보유)로
평가했으나, 이는 **rag-ent-api(Enterprise 비공개 레이어)의 E-21/E-22가 done인 상태를
반영하지 못한 값**이다. 문서 상단에 "본 제품 열 (E) = Enterprise 배포 기준"이라고 명시돼
있으므로, E 기준으로는 아래 내용으로 갱신되어야 한다.

- **E-21 (이미지 캡셔닝 + PDF OCR 폴백, done)**: RapidOCR(`Det.model_type=server`, 한국어
  Rec 모델)로 스캔 PDF/순수 이미지 OCR. VLM(ollama/openai)으로 PDF·DOCX 임베디드 이미지
  캡셔닝.
- **E-22 (PDF 표 구조 보존 파싱, done)**: RapidTable(SLANet-plus, ONNX)로 표를 markdown
  재구성. vector PDF는 표 bbox와 겹치는 본문 텍스트를 제외해 본문/표 중복 저장을 실측으로
  검증(`ATD00005_2605.pdf` 표 6개 정확 추출, 본문 중복 없음 확인). 스캔 PDF도 RapidTable
  내부 OCR로 표 추출.
- rag-ent-api는 `RapidLayout`의 `DOCLAYOUT_DOCSTRUCTBENCH` 모델(DocLayout-YOLO ONNX
  변환)도 표 영역 탐지용으로 이미 사용 중(`table_region_detector.py`).

**정정된 평가**: "하(X)" → "중" 상향. "LightRAG에도 본 제품의 최대 격차가 그대로
적용된다"는 서술은 삭제 필요.

**남은 실제 격차** (LightRAG/MinerU 대비, 2절 참고):
- 수식(formula) 인식 없음
- 문서 전체 read-order 재구성(멀티컬럼, 헤딩 계층 → markdown) 없음 — RapidLayout은 표
  영역 탐지 용도로만 스코프가 한정됨
- 스캔 페이지의 본문/표 텍스트 중복 미해결(E-22 known limitation, design 문서 §8)

---

## 2. MinerU vs RapidOCR/RapidLayout/RapidTable

### 2.1 핵심 발견 — 레이아웃 모델은 사실상 동일 계열

`RapidLayout`의 `DOCLAYOUT_DOCSTRUCTBENCH`는 **`DocLayout-YOLO`를 ONNX로 변환한 것**이고,
OmniDocBench 벤치마크 자료에 따르면 **MinerU가 pipeline 백엔드에서 레이아웃 검출에 쓰는
핵심 모델도 동일한 DocLayout-YOLO**다. 즉 rag-ent-api의 레이아웃 검출 엔진은 MinerU가
쓰는 것과 같은 계열의 모델을 RapidAI가 ONNX로 경량화해 재포장한 것이다 — 열등한 대체재가
아니라 코어 모델은 동급.

### 2.2 항목별 비교

| 항목 | MinerU (pipeline 백엔드) | RapidOCR + RapidLayout + RapidTable |
|---|---|---|
| 레이아웃 검출 모델 | DocLayout-YOLO | DocLayout-YOLO(ONNX 변환) — 원본 모델 동일 |
| 레이아웃 출력 범위 | 문서 전체 읽기 순서 재구성(멀티컬럼·헤딩 계층·리스트) | 표 영역(bbox) 탐지 용도로 스코프 한정 |
| 텍스트 OCR | 자체 조합, 84개 언어 | PaddleOCR 계열을 ONNX 변환 — 벤치마크 1위는 PaddleOCR 원본, RapidOCR은 근사 정확도 |
| 표 인식 | OmniDocBench에서 두각 | RapidTable(OCR 기반) — 표 인식 mAP 약 82.5로 동 벤치마크 최상위권으로 인용됨 |
| 수식 인식(LaTeX) | O (UniMERNet) | 없음 — 확인된 격차 |
| 리소스 | GPU 권장(YOLOv8/UniMERNet 성분), CPU 전용은 `pipeline` 백엔드로 가능하나 처리량 낮음 | 전 구간 ONNX, CPU로 동작(RapidOCR ~100~150MB, PaddleOCR ~430MB 대비 경량) |
| 언어 | 84개 언어 | 한국어 고정 튜닝(설정 노출 안 함 — 잘못 끄면 정확도 붕괴하는 값) |
| 공통 약점 | 세로쓰기 미지원, 다단계 헤딩 미지원, 복잡한 표 행/열 오류 | 스캔 페이지 본문/표 중복 미해결, 이미지 픽셀 dedup 없음 |

### 2.3 MinerU 자체 배포 옵션 조사

- **GPU 요구**: `pipeline` 백엔드는 CPU 전용 가능(저볼륨 온디맨드용). 단 레이아웃(YOLOv8)과
  수식(UniMERNet)은 GPU 필요. VLM 백엔드(고정확도 경로)는 GPU 필수.
- **Mac 지원**: `vlm-mlx-engine`/`vlm-auto-engine`으로 Apple Silicon MLX 가속 지원
  (macOS 14.0+, `vlm-transformers` 대비 100~200% 속도 향상). CPU-only(`-b pipeline`)도
  가능.
- **Ollama 연동**: 공식 미지원. `vlm-http-client`가 OpenAI 호환 서버에는 연결 가능하나,
  MinerU 전용 파인튜닝 VLM(`opendatalab/MinerU2.5-*`) 가중치가 Ollama(GGUF)로 배포된 사례
  없음 — 프로토콜은 맞아도 모델이 없는 상태.
- **Mac에서 vLLM으로 MinerU 직접 서빙**: 시도해도 실패 가능성 높음.
  - `vllm-metal`(vllm-project 공식 커뮤니티 플러그인) 지원 VLM은 Qwen3-VL/PaddleOCR-VL
    (둘 다 experimental)뿐 — MinerU2.5-VL은 Qwen2-VL 계열이라 **미지원**.
  - `mineru-vl-utils[vllm]`가 요구하는 `--logits-processors mineru_vl_utils:MinerULogitsProcessor`
    커스텀 플래그도 vllm-metal 문서에 언급 없음.
  - 결론: Mac에서는 vllm-metal 우회보다 MinerU 자체 내장 `vlm-auto-engine`(MLX)을 쓰는 게
    검증된 경로.

---

## 3. LightRAG 아키텍처

### 3.1 배포 구조 — 단일 모놀리식 서버

LightRAG은 **REST API + WebUI + 인증을 전부 포함한 단일 API 서버 프로세스**로 동작한다.
본 제품(rag-platform/rag-admin/rag-api/rag-ent-api 4개 서비스로 관심사 분리 + Dagster
오케스트레이션 + Redis 이벤트 큐)과의 핵심 차이:

| 축 | 본 제품 | LightRAG |
|---|---|---|
| 서비스 구성 | 4개 프로세스(프런트/콘솔/코어엔진/인증+RBAC) | 단일 API 서버(인증 포함) |
| 오케스트레이션 | Dagster(run 관측성, 재시도 UI, launcher 선택) | 없음 — asyncio 기반 in-process concurrency(`MAX_ASYNC_LLM`/`MAX_PARALLEL_INSERT` env var) |
| 이벤트 큐 | Redis(ingest/delete 큐, Dagster 없이도 QueueWorker로 직접 실행 가능) | 없음 — 요청이 오면 같은 프로세스에서 바로 async 처리, `pipeline_status`(in-memory shared dict)로 동시 writer만 조율 |
| 원본 파일 보관 | MinIO(S3 호환) 별도 계층 | 문서화된 원본 영속 저장 계층 없음 |
| 스토리지 역할 분리 | 인프라 파일 단위로 엄격 고정(하드 룰) | KV/Vector/Graph/DocStatus 4개 논리 타입을 Postgres/Mongo/OpenSearch 등에 자유 매핑 가능 |

R2R보다도 더 모놀리식에 가깝다(R2R은 최소한 Dashboard가 분리돼 있음). 가볍게 띄우긴
쉽지만 "조립형/임베드형으로 쪼개 쓰기"는 본 제품 대비 어렵다.

---

## 4. LightRAG 그래프 처리 방식

원문: [arXiv:2410.05779](https://arxiv.org/abs/2410.05779) "LightRAG: Simple and Fast
Retrieval-Augmented Generation" (Guo et al., HKUDS)

### 4.1 인덱싱 — 추출 → gleaning → 병합, 커뮤니티 요약 생략

1. **엔티티/관계 추출** `R(·)`: 청크 단위로 LLM 호출, 개체(이름·타입·설명)와 관계 튜플 추출.
2. **Gleaning(반복 재추출)**: "놓친 게 있는가?" LLM 재질의 패스(논문 실험은 1회 고정).
3. **LLM Profiling** `P(·)`: 각 엔티티/관계에 key-value 쌍 생성 — key는 검색용 단어/구,
   value는 원문 요약 문단.
4. **Deduplication** `D(·)`: 서로 다른 텍스트 조각에서 나온 동일 엔티티/관계를 병합 —
   그래프 크기를 줄여 이후 그래프 연산 오버헤드를 낮추는 목적.
5. **점진적 업데이트**: 새 문서 `D'`도 동일 인덱싱 함수로 처리한 뒤, 기존 노드/엣지
   집합과 **union**만 수행 — 전체 재구축 없음.

**Microsoft GraphRAG과의 결정적 차이**: GraphRAG은 Leiden 알고리즘으로 커뮤니티를
클러스터링하고 커뮤니티마다 LLM 요약 리포트를 만들어 둔다(비용·시간이 큼). LightRAG은 이
사전 커뮤니티 요약 단계 자체를 생략하고 엔티티/관계를 그대로 인덱싱한다 — "GraphRAG의
가벼운 대안"이라는 표현이 이 지점에서 나온다.

### 4.2 쿼리 시점 — Dual-Level Retrieval

- **Low-level(저수준)**: 질의에서 구체적 엔티티 키워드 추출 → 그래프 노드와 직접 매칭 →
  특정 사실/디테일 정밀 답변.
- **High-level(고수준)**: 질의에서 주제/개념 키워드 추출 → 관계·테마 임베딩과 매칭 →
  여러 엔티티에 걸친 종합 답변.
- **키워드 매칭 → 고차 관련성 확장**: 매칭된 노드/엣지의 1-hop 이웃까지 포함해 컨텍스트
  확장(논문 §3.2 "Incorporating High-Order Relatedness").
- Ablation 결과(논문 Table 2): low-level만 쓰면 포괄성(comprehensiveness) 급락, high-level만
  쓰면 세부 정확도 저하 — 두 레벨을 합친 hybrid 모드가 균형적으로 가장 우수.
- 흥미로운 부가 발견: 원문 텍스트를 검색 컨텍스트에서 제거한 `-Origin` variant가 일부
  데이터셋(Agriculture, Mix)에서 오히려 성능이 향상됨 — 그래프 인덱싱 단계에서 핵심 정보가
  이미 충분히 추출되고, 원문의 노이즈가 오히려 방해가 될 수 있음을 시사.

### 4.3 "빠르다" 주장의 실제 근거 (논문 §3.4, §4.5, Legal 데이터셋 기준)

측정 조건: Legal 데이터셋(문서 94개, 508만 토큰), GPT-4o-mini, gleaning=1, chunk size 1200,
nano vector database.

**(1) 쿼리 시점 비용**

| | GraphRAG | LightRAG |
|---|---|---|
| 토큰 | 610 × 1,000 = 610,000 | 100 미만 |
| API 호출 | 커뮤니티 수만큼(수백 회) | 1회 |

GraphRAG은 1,399개 커뮤니티 중 610개(level-2)를 쿼리마다 순회(brute-force traversal)해야
함. LightRAG은 쿼리 키워드 추출(1회 LLM 호출) 후 벡터 매칭으로 엔티티/관계를 직접
검색 — 커뮤니티 순회 자체가 없음.

**(2) 증분 업데이트 비용**

- GraphRAG: 새 문서 추가 시 기존 커뮤니티 구조를 해체하고 **전체 재생성** 필요. 커뮤니티
  리포트당 약 5,000토큰 × 1,399개 커뮤니티 × 2(기존+신규) ≈ **1,399만 토큰**.
- LightRAG: 신규 추출 결과를 기존 그래프에 union 병합만 — 추출 오버헤드(`T_extract`)만
  발생, 재생성 비용 없음.

**근본 메커니즘** (논문 §3.4): 인덱싱 LLM 호출 수는 `total_tokens / chunk_size`에
비례할 뿐 추가 오버헤드가 없고, 검색은 "커뮤니티 기반 순회 대신 엔티티·관계 직접 검색"으로
오버헤드를 줄인다.

**주의**: 이 수치는 Legal 데이터셋 1개, 특정 LLM/설정 조합에서 측정된 값 — 커뮤니티
개수·리포트 토큰 수는 이 실험 세팅에 종속적이라 그대로 일반화하기 어렵다.

### 4.4 정확도 리스크 — 논문이 검증하지 않은 부분

Table 1/2의 정확도 비교는 전부 **코퍼스를 한 번에(one-shot) 인덱싱한 결과**에 대한
평가다. "증분 업데이트를 여러 번 거친 뒤에도 검색 정확도가 유지되는가"는 논문 어디에도
벤치마크가 없다 — 비용 절감(§4.5)과 정확도 유지가 별개 주장이라는 점에 주의.

실제 리스크는 재클러스터링 생략이 아니라 **엔티티 중복 제거 품질**에 있다: `Dedupe`
함수는 "동일" 엔티티/관계를 병합하는데, 서로 다른 배치에서 같은 실체가 다른 이름으로
추출되면(예: "Apple Inc." vs "Apple") 병합되지 않고 그래프에 중복 노드가 쌓일 수 있다.
그래프 생성 프롬프트(논문 Figure 4)는 엔티티명을 대문자화(capitalize)하라고만 지시할 뿐
별칭/약어 정규화는 요구하지 않는다. 인제스트를 여러 번 나눠서 할수록 이 누적 효과가
커지는데, 논문 실험은 코퍼스를 한 번에 인덱싱했으므로 이 누적 효과 자체를 측정하지 못했다.

---

## 5. 본 제품에 도입한다면

### 5.1 권장 방향

LightRAG를 라이브러리·서비스로 통째로 가져오지 않는다 — LightRAG은 KV/Vector/Graph/
DocStatus 저장소를 자체 소유하려는 구조라, 인프라 파일을 역할별로 엄격히 분리하는 하드
룰(`s3.py`/`redis.py`/`postgres.py`/`qdrant.py`)과 충돌하고 문서 저장이 이중화된다.
대신 "추출+병합, 커뮤니티 요약 생략" **패턴만 참고해 우리 파이프라인에 맞는 별도 Step으로
새로 구현**하는 방향을 권장.

### 5.2 필요 작업 (레이어별)

| 레이어 | 작업 |
|---|---|
| `infra/` | 그래프 DB 클라이언트 신설(`graph.py` 가칭, Neo4j/Memgraph 등) — 하드 룰 6 표에 행 추가 |
| `config/settings.py` | `GraphSettings`(연결 정보) + `GraphExtractionSettings`(enabled 기본 false, EXTRACT LLM provider, gleaning 횟수) 신규, `settings.yaml` 3종 갱신 |
| `pipeline/steps/` | `graph_extract.py` 순수 함수 신규 — `extract_graph(nodes, kb_id, max_gleaning) -> GraphExtractionResult`. LLM provider 분기는 `embed.py`의 `build_embed_model()` 패턴 재사용. 저장(write)은 하지 않음 |
| `defs/ops/` | `graph_extract_op.py` — `chunk()` 출력을 받아 `embed`와 병렬 실행 가능한 위치에 배치 |
| `rag/` | (별도 스코프 권장) dual-level retrieval을 실제 검색에 반영하려면 `merger.py`에 그래프 조회 결과를 세 번째 소스로 합치는 로직 필요 — 저장 스코프와 분리해서 후속 작업으로 분리 권장 |
| 테스트 | `conftest.py`에 `mock_extract_llm` 픽스처 신규 |
| 문서 | `docs/internal/design/data-schema.md` 갱신(신규 스키마) |

### 5.3 핵심 리스크

1. **LLM 비용/지연시간 상시 발생** — 인제스트마다 청크당 추출(1~2회) + gleaning + 병합
   요약(LightRAG 방식 그대로 가져올 경우)까지 LLM 호출이 누적. LightRAG도 동일 구조라
   "가볍다"는 GraphRAG 대비 상대 평가이지, LLM 호출 자체가 적다는 뜻이 아님.
2. **엔티티 중복 누적** — 4.4절 리스크가 그대로 적용됨. 이름 정규화/별칭 해소를 처음부터
   설계에 넣거나, 최소한 PoC 단계에서 "증분 인제스트 여러 번 후 그래프 품질 저하 여부"를
   검증하는 절차 포함 필요.
3. **수요 미검증** — 경쟁분석 문서 기준으로도 GraphRAG은 Phase 2, 낮은 우선순위. 인프라
   투자 전에 비용/품질을 가볍게 재보는 PoC가 정식 backlog보다 선행되어야 함.

---

## 참고 자료

- [LightRAG: Simple and Fast Retrieval-Augmented Generation (arXiv:2410.05779)](https://arxiv.org/abs/2410.05779)
- [GitHub - HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)
- [HKUDS/LightRAG — Document Processing Pipeline (DeepWiki)](https://deepwiki.com/HKUDS/LightRAG/2.2-document-processing-pipeline)
- [Under the covers with LightRAG: Extraction (Neo4j Blog)](https://neo4j.com/blog/developer/under-the-covers-with-lightrag-extraction/)
- [Community detection — Microsoft GraphRAG docs](https://www.mintlify.com/microsoft/graphrag/concepts/community-detection)
- [GitHub - opendatalab/MinerU](https://github.com/opendatalab/mineru)
- [MinerU Quick Start / Quick Usage](https://opendatalab.github.io/MinerU/quick_start/)
- [GitHub - RapidAI/RapidLayout](https://github.com/RapidAI/RapidLayout)
- [OmniDocBench v1.5 Benchmark](https://www.emergentmind.com/topics/omnidocbench-v1-5)
- [GitHub - vllm-project/vllm-metal](https://github.com/vllm-project/vllm-metal)
- rag-ent-api `.claude/backlogs/E-21-image-captioning-ocr-fallback.md`,
  `E-22-pdf-table-layout-parsing.md` (비공개 저장소, done 상태 확인용)
