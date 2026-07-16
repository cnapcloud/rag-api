# 이미지 캡셔닝 + PDF OCR 폴백

> 요건: [prd.md §2](../requirement/prd.md#2-문서-인제스트) (파이프라인 단계 2. 파싱)

`pipeline/step/parse.py`는 이 기능을 위해 수정하지 않는다 — [parser-registry.md](parser-registry.md)
(US-41)의 등록 API(`register_parser`/`register_post_processor`)를 호출하는 플러그인 `register()`
함수 하나로 전부 배선한다.

- `.pdf` 항목은 등록 시점에 `PyMuPDFReader()`를 상속한 `PyMuPDFOCRFallbackReader()`(§2)로
  교체 등록한다. 나머지 포맷(`.docx`/`.md`/`.txt`/`.hwp`/`.html`/`.htm`/`.rst`)은 재등록하지
  않으므로 레지스트리 기본값이 그대로 유지된다.
- 이미지 캡셔닝은 `register_post_processor()`로 등록한 함수가 `reader.load_data()` 이후 공통
  적용된다(§2) — 어떤 리더가 텍스트를 뽑았든 상관없이 동일하게 적용되므로 어떤 리더가 등록돼
  있는지와 무관하다.
- 순수 이미지 파일(case B)은 이미지 확장자마다 `register_parser(ext, VLMCaptionReader())`를
  호출하는 것뿐이다(§6).

## 1. 개요

`parse_op`은 현재 이미지를 완전히 무시한다. 다이어그램·차트 중심 문서에서 핵심 정보가 유실되고,
텍스트 레이어가 없는 스캔 PDF는 빈 문서로 색인된다. 이 문서는 두 가지를 다룬다.

1. **이미지 캡셔닝** — 문서에 포함된 이미지(및 이미지 파일 자체)를 vision 모델로 설명해 검색 가능한
   텍스트로 변환. 임베디드 이미지 추출은 **PDF·DOCX만 1차 범위**로 한다 — 현재 라이브러리로 바로
   되는 포맷만 우선 구현하고, HTML/MD/HWP는 별도 파싱 로직이 필요해 후속 과제로 미룬다(§2, §11).
2. **PDF OCR 폴백** — 텍스트 추출 결과가 부족한 스캔 PDF를 전용 OCR 엔진으로 페이지 단위 전사

두 기능은 목적이 달라 **서로 다른 모델을 쓴다** — 캡셔닝은 "이 이미지가 무엇을 보여주는가"를
설명(summarize)하는 작업이고, OCR 폴백은 "이 페이지에 어떤 글자가 적혀 있는가"를 있는 그대로
전사(transcribe)하는 작업이다. 초안에서는 vision 모델(qwen2.5vl) 하나로 두 문제를 풀려 했으나,
생성형 VLM으로 전사를 시키면 실측(§3.1)에서 확인된 환각·비재현성 문제가 본문 텍스트 자체에
그대로 노출된다. 그래서 OCR 폴백은 인식 기반 전용 OCR 엔진(§3)으로 분리한다 — 환각 리스크 자체를
구조적으로 없앤다(§8). on/off는 `settings.yaml` 전역 opt-in(`ingestion.pdf_ocr_fallback.enabled`,
§5)으로 두고, KB 단위 스키마 변경은 하지 않는다.

## 2. 처리 흐름

두 가지 입력 케이스가 있다.

```
parse(doc_id, storage_key)
        │
        ├────────────────────────────────┬─────────────────────────────────┐
        │  case A: 이미지 "포함" 문서        │  case B: 순수 이미지 파일
        │  (PDF/DOCX만 — 1차 범위)          │  (.png/.jpg/... 자체가 문서)
        ▼                                  ▼
   등록된 리더.load_data()               register_parser(ext, VLMCaptionReader())
   로 텍스트 추출 (기존과 무변경)          (신규 등록 — parser-registry.md §3 절차, §6)
        │                                  │
   텍스트 Document 생성                     │
        │                                  │
        ▼                                  │
   문서 언어 판별 (§3.2)                     │
   detect_language(text_document.text)      │
   -> "ko" | "en" 등                        │  ※ case B는 판별 대상 텍스트가
        │                                  │    없어 이 단계 없음 — default_language 사용
        ▼                                  │
   이미지 참조(xref) 목록 조회               │
   (PyMuPDF page.get_images() — .pdf /      │
    python-docx inline_shapes — .docx.      │
    image_captioning.enabled가 false면      │
    이 단계 전체 스킵)                       │
        │                                  │
        ▼                                  │
   이미지 바이트 추출 (메모리)                │
   (PyMuPDF doc.extract_image(xref)         │
    -> {"image": bytes, "ext": str} /       │
    python-docx: rels[rId].blob             │
    — 디스크에 다시 쓰지 않고 bytes로 유지)   │
        │                                  │
        ▼                                  │
   qwen2.5vl:3b 캡셔닝  ◄────────────────────┘
   (언어별 프롬프트 — case A는 판별된 언어,
    case B는 default_language, §3.2 / embedding과
    동일하게 provider: ollama | openai 스위치)
        │
        ▼
   캡션 Document 생성
   metadata: {type: "image_caption", page, image_index}
        │
        ▼
   텍스트 Document + 캡션 Document 리스트 병합   (parse() 반환값, 형태 불변)
        │
        ▼
   chunk() → embed() → upsert() → set_indexed()   (기존 Op, 무변경)
```

PDF OCR 폴백은 case A의 하위 분기이며, `.pdf` 리더 내부에서만 발생한다 — `parse()` 본체나 다른
포맷 리더는 이 로직을 알 필요가 없다.

```
PyMuPDFOCRFallbackReader.load_data(file, extra_info)
        │
        ├─ pdf_ocr_fallback.enabled == False (전역 opt-in 꺼짐, 기본값) ──► 그대로 반환
        │
        └─ pdf_ocr_fallback.enabled == True (전역 opt-in 켜짐)
                │
                ▼
           페이지별 텍스트 추출 결과 확인
                │
                ├─ 평균 글자 수 >= pdf_ocr_fallback.min_chars_per_page  ──► 그대로 반환 (정상 텍스트 PDF)
                │
                └─ 평균 글자 수 < min_chars_per_page (스캔본으로 판단)
                        │
                        ▼
                   OCR 엔진 호출 (§3, 페이지를 이미지로 렌더링 -> PaddleOCR 전사)
                        │
                        ▼
                   텍스트 Document 생성 (page_label 메타데이터 유지)
```

```python
# pipeline/plugins/image_ocr.py — parser_plugins에 "rag_api.pipeline.plugins.image_ocr:register"로 등록
class PyMuPDFOCRFallbackReader(PyMuPDFReader):
    """PyMuPDFReader 그대로 쓰되, 텍스트가 부족한 스캔 PDF만 OCR로 대체한다."""

    def load_data(self, file_path: Path, extra_info: dict | None = None) -> list[Document]:
        documents = super().load_data(file_path, extra_info)  # 기존 PyMuPDF 추출, 변경 없음
        if not get_settings().ingestion.pdf_ocr_fallback.enabled:
            return documents

        avg_chars = sum(len(d.text) for d in documents) / len(documents)
        if avg_chars < get_settings().ingestion.pdf_ocr_fallback.min_chars_per_page:
            return _ocr_fallback(file_path)  # pipeline/utils/ocr.py
        return documents


def register() -> None:
    """parser-registry.md §3 절차를 따르는 이 기능의 유일한 진입점."""
    from rag_api.pipeline.step.parser import register_parser, register_post_processor

    register_parser(".pdf", PyMuPDFOCRFallbackReader())   # 기본 PyMuPDFReader() 대체 — 나머지
                                                            # 포맷은 등록하지 않으므로 무변경(§1)
    register_post_processor(caption_embedded_images)       # §2 case A 공통 후처리
    for ext in IMAGE_EXTENSIONS:                            # §6 case B
        register_parser(ext, VLMCaptionReader())
```

다른 모델 기반 파서(캡셔닝의 `vlm.py`)와 동일하게 `get_settings()`를 `load_data()` 내부에서 직접
호출한다 — 부모 클래스 `PyMuPDFReader`의 시그니처(`load_data(file_path, extra_info=None)`)를 그대로
따르므로 `SimpleDirectoryReader`나 `parse()` 오케스트레이션 쪽 변경이 필요 없다. 판단은 **문서
단위**로만 한다 — 한 문서 안에 텍스트 페이지와 스캔 페이지가 섞인 경우(페이지 단위 판단)는
비범위다(§11).

**두 조건(전역 opt-in AND 글자 수 부족)이 모두 참이어야 OCR 엔진이 호출된다** — 꺼져 있으면 글자
수와 무관하게 항상 PyMuPDF 결과 그대로, 켜져 있어도 텍스트가 충분하면 OCR을 타지 않는다. 문서 단위
수동 오버라이드는 없다 — 있었던 `ingestion.parser_strategy: {pdf: "ocr"}` 설계(R2R의
`parser_overrides`류)는 폐기한다. 이유는 §8 참고 — 강제 지정은 "대체"가 아니라 항상 "교체"라서,
텍스트가 멀쩡한 문서에 잘못 켜면 정확한 원본 텍스트를 OCR 결과로 덮어쓰는 사고가 난다. 자동
판단이면 이 사고 자체가 구조적으로 발생하지 않는다.

## 3. 모델 선택

캡셔닝(설명)과 OCR 폴백(전사)은 목적이 달라 별도 모델/엔진을 쓴다.

| 용도 | 기본 모델/엔진 | 근거 |
|---|---|---|
| 이미지 캡셔닝 | `qwen2.5vl:3b` (Ollama) | Qwen-VL 계열은 문서·차트·다이어그램 설명에 강함. 8B(`qwen3-vl:8b`)보다 지연이 크게 낮아 인제스트 파이프라인에 적합 |
| PDF OCR 폴백(전사) | PaddleOCR (`korean` 언어팩) | 인식 기반 엔진 — 생성형 VLM과 달리 존재하지 않는 내용을 지어내는 환각이 구조적으로 없음(오인식은 가능). 한국어 인식 정확도가 Tesseract 대비 우수해 채택. 로컬 CPU/GPU 추론, 외부 API 의존 없음 |

캡셔닝은 최상위 `provider.name: ollama | openai` 설정을 `embedding`과 공유해서 따른다 —
`pipeline/step/embed.py`의 `build_embed_model()`과 동일한 if/elif 분기를 `vlm.py`에도 둔다:

```python
# pipeline/utils/vlm.py
def caption_image(image_bytes: bytes, prompt: str) -> str:
    provider = get_settings().provider
    cfg = get_settings().ingestion.image_captioning

    if provider.name == "ollama":
        # OllamaMultiModal 등, cfg.model + provider.ollama_url 사용
        ...
    elif provider.name == "openai":
        # OpenAI vision 클라이언트, cfg.model + provider.openai_api_key 사용
        ...
    else:
        raise ConfigError(f"Unknown provider: {provider.name}")
```

알 수 없는 provider에 `ConfigError`(하드룰 1, `conventions/05-exception-handling.md` "잘못된
provider" 예시와 동일 케이스)를 내는 것까지 `build_embed_model()`과 완전히 동일한 패턴이다.

OCR 폴백은 캡셔닝과 별도 축이라 provider 전환 대상이 아니다 — 필요 시 `pdf_ocr_fallback.engine:
paddleocr | tesseract`로 엔진 자체를 바꾼다(§5).

### 3.1 실측 성능 — 이미지 캡셔닝 (`qwen2.5vl:3b`, 로컬 Ollama, M-series Mac)

`experiments/vlm-poc/`(git 미포함, 로컬 PoC)에서 측정. 합성 이미지(깨끗한 차트·렌더링된 문서)와
실사진(각도·겹침·가림 있는 인증서 촬영본) 둘 다 테스트.

이 실험 당시에는 OCR 폴백도 같은 VLM으로 처리하는 안을 검토 중이라 "전사" 케이스도 함께
측정했다. 이후 §1·§8 사유로 OCR 폴백은 PaddleOCR로 분리했으므로, 아래 "전사" 행은 **채택된
설계가 아니라 그 결정에 이른 근거 기록**이다 — 캡셔닝(설명) 행만 현재 설계에 유효하다.

| 케이스 | wall time | 모델 로드 | 토큰 수 | tok/s |
|---|---|---|---|---|
| 차트 캡셔닝 (합성) | 9.28s | 5.01s (최초) | 88 | 90.2 |
| ~~한글 문서 OCR (합성)~~ | 4.85s | 0.12s | 157 | 89.2 |
| 실사진 설명 (영어 프롬프트) | 8.69s | 2.97s (재로드) | 45 | 91.7 |
| ~~실사진 전사 (영어 프롬프트)~~ | 1.01s | 0.12s | 67 | 90.5 |
| 실사진 설명 (한국어 프롬프트) | 1.69s | 0.15s | 118 | 89.4 |
| ~~실사진 전사 (한국어 프롬프트)~~ | 1.76s | 0.12s | 133 | 89.5 |

- 토큰 생성 속도는 언어·내용과 무관하게 **89~92 tok/s로 일정**.
- 모델 콜드 스타트(최초 로드)는 3~5초 1회성 비용. 이후 호출은 로드 비용 없이 바로 처리.
- **정상 상태(warm) 기준 이미지 1장당 처리 시간은 응답 길이에 비례해 1~5초.**
  `max_images_per_doc`(§5) 상한이 실제로 지연을 좌우하는 값임을 확인.
- 한국어 프롬프트도 문제없이 동작 — 지시어를 한국어로 주면 한국어로, "원문 언어 유지"라고 지시하면
  전사 대상 언어(영어)를 그대로 유지하며 응답. 프롬프트 언어에 따른 처리 속도 차이는 없음.

### 3.2 캡션 언어 결정

위 실측(§3.1)에서 확인됐듯 캡션 언어는 **프롬프트에 지시한 언어를 따라간다** — 모델이 이미지
내용을 보고 알아서 문서 언어에 맞추는 게 아니다. 그래서 문서 언어를 미리 판별해 프롬프트에
명시적으로 넣어줘야 한다. 이미지가 나온 경로(case A/B)에 따라 판별 방법이 다르다.

- **case A (문서 내 임베디드 이미지)** — 같은 문서에서 이미 추출된 텍스트 Document(§2, 이미지 추출보다
  먼저 생성됨)가 있으므로, 그 텍스트로 언어를 판별해 그대로 프롬프트에 반영한다. 문서 전체가 한
  언어라고 가정한다(문서 내 언어가 섞인 경우는 비범위, §11).
  ```python
  language = detect_language(text_document.text)  # pipeline/utils/lang.py, 예: "ko" | "en"
  caption = caption_image(image_bytes, prompt=build_caption_prompt(language))
  ```
- **case B (순수 이미지 파일)** — 판별에 쓸 문서 텍스트 자체가 없다. 이미지 안에 글자가 있을 수도,
  아예 없을 수도(사진) 있어 사전 판별이 불가능하다. `ingestion.image_captioning.default_language`
  설정값(기본 `ko`, §5)을 그대로 쓴다 — 이미지 내용으로 언어를 추측하려 하지 않는다.

언어 판별은 `langdetect`(순수 파이썬, 신규 의존성) 같은 가벼운 라이브러리로 충분하다 — 문서 언어가
한국어/영어 위주인 이 제품의 실제 코퍼스 특성상 정교한 판별기가 필요하지 않다. 판별 결과는
ISO 639-1 코드(`ko`, `en` 등)로 통일하고, `build_caption_prompt(language)`가 이를 "Describe this
image concisely in Korean." 같은 프롬프트 문장으로 변환한다.

## 4. 이미지 임베딩 방식 — 캡션 텍스트 임베딩 vs 멀티모달 벡터

이미지를 검색 가능하게 만드는 방법은 두 가지가 있다.

- **A. 캡션 → 텍스트 임베딩 (이 문서가 채택)**: vision 모델이 생성한 캡션 텍스트를 기존 dense(bge-m3)
  + sparse(BM25) 파이프라인에 그대로 태운다. 새 인프라 없이 기존 hybrid 검색으로 "이 다이어그램이
  무엇에 관한 것인가"를 바로 검색 가능하게 만든다.
- **B. 멀티모달 벡터 (CLIP/SigLIP 계열)**: 이미지를 직접 벡터화해 "시각적으로 유사한 이미지 검색"을
  지원한다.

**B는 이번 범위에서 제외한다.** 이유:

- 현재 dense 임베딩 모델(bge-m3)은 텍스트 전용이라, B를 도입하려면 별도 임베딩 모델 + Qdrant
  스키마에 별도 벡터 필드/컬렉션이 필요하다 ([data-schema.md](data-schema.md) 변경 대상).
- `rag/retriever`·`rag/merger`(RRF)·`rag/reranker`(Jina, 텍스트 전용 API)가 모두 텍스트 벡터를
  전제로 짜여 있어, 이미지 벡터를 섞으려면 검색 파이프라인 전체를 확장해야 한다 — 이 문서(파서
  레이어) 범위를 크게 벗어난다.
- 이 RAG 시스템의 유스케이스는 "문서 내용에 대한 질의 응답"이지 "비슷하게 생긴 이미지 찾기"가
  아니다. A만으로 다이어그램·차트의 *의미*는 이미 검색 가능해지므로, 목표 대비 B의 추가 가치가
  불확실하다.

A를 선택하면 하위 파이프라인(`chunk`/`embed`/`upsert`)이 캡션 Document를 일반 텍스트 Document와
구분하지 못해도 무방하다 — `metadata.type: "image_caption"`으로 검색 결과에서만 구분한다. B는 향후
"이미지 유사도 검색"이 실제 요구사항으로 확인되면 별도 design 문서로 다룬다.

## 5. 설정 스키마

`provider`/`ollama_url`/`openai_api_key`는 `embedding`과 `image_captioning`이 공유하는 최상위
블록으로 뺐다 — 두 기능 모두 "ollama | openai 중 어디에 붙을지"를 같은 축으로 고르고, 배포 하나당
Ollama 서버·OpenAI 키는 보통 하나뿐이라 기능별로 중복 선언할 이유가 없다(상세 근거는 아래 표
이후 설명 유지). `model`은 provider별로 필드를 나누지 않고 하나만 두고, provider를 바꿀 때
값도 그에 맞게 같이 바꿔 쓴다.

```yaml
provider:
  name: ollama                # ollama | openai — embedding, ingestion.image_captioning 공통
  ollama_url: "http://localhost:11434"
  openai_api_key: ""

embedding:
  model: "bge-m3"              # provider에 맞는 모델명 (ollama: bge-m3 / openai: text-embedding-3-small)
  vector_size: 1024

ingestion:
  image_captioning:
    enabled: false              # 기본 비활성화 (opt-in)
    model: "qwen2.5vl:3b"       # provider에 맞는 모델명 (ollama: qwen2.5vl:3b / openai: gpt-4o-mini)
    temperature: 0.1             # 낮게 고정 — 재현성 확보 목적 (§8 참고)
    max_images_per_doc: 20      # 대용량 스캔 PDF/이미지 다수 문서 지연 상한
    max_concurrent_tasks: 5     # 이미지별 VLM 호출 동시성 (asyncio.Semaphore)
    default_language: ko        # case B(문서 텍스트 없음) 캡션 언어 (§3.2). ISO 639-1

  pdf_ocr_fallback:
    enabled: false              # 기본 비활성화 (opt-in)
    engine: paddleocr           # paddleocr | tesseract
    language: korean            # PaddleOCR 언어팩
    min_chars_per_page: 50      # 페이지 평균 글자 수 미달 시 OCR 경로로 자동 전환
```

`embedding`을 `ingestion` 하위가 아니라 최상위에 남긴 이유: 같은 임베딩 모델을 `retrieval`의 질의
벡터화(hybrid 검색 dense 축, `rag/retriever.py`)에서도 그대로 재사용하기 때문이다 — 인제스트
전용 설정이 아니다.

on/off 스위치는 `image_captioning`과 동일하게 `settings.yaml` 전역 opt-in이다 — KB별로 스키마를
따로 두지 않는다. 켜면 모든 KB의 스캔 PDF에 동일하게 적용된다.

`image_captioning`과 `pdf_ocr_fallback`을 분리한 이유: 전자는 문서 내 임베디드 이미지, 후자는 PDF
페이지 자체가 대상이라 활성화 여부를 독립적으로 켜고 끌 수 있어야 한다 (예: 캡셔닝은 원치 않지만
스캔 PDF 텍스트화는 필요한 경우). 둘 다 전역 opt-in이라는 점은 같다.

## 6. 지원 확장자 변경

이미지 확장자마다 `register_parser(ext, VLMCaptionReader())`를 호출해 case B(순수 이미지 파일)를
지원한다(§2 `register()`). `parse.py`의 `supported_extensions()`([parser-registry.md](parser-registry.md)
§2.1)가 레지스트리를 그대로 조회하므로 별도 상수를 따로 갱신할 필요가 없다.

```python
IMAGE_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"})
```

`image_captioning.enabled: false`인 상태에서는 `register()`가 이미지 확장자를 애초에 등록하지
않으므로, 이미지 파일 업로드 시 `parse()`의 기존 미지원 형식 검증(`supported_extensions()`
미포함 -> `IngestValidationError`)이 그대로 적용된다 — 별도 분기를 추가하지 않는다.

## 7. 수정 파일

| 파일 | 변경 내용 |
|---|---|
| `pipeline/step/parse.py` | **무변경.** 이 기능은 [parser-registry.md](parser-registry.md)(US-41)의 등록 API만으로 배선된다 — `_get_file_extractor()`/`SUPPORTED_EXTENSIONS` 자체가 이제 존재하지 않는다(US-41에서 제거됨) |
| `pipeline/plugins/image_ocr.py` | 신규 — 이 기능의 유일한 진입점 `register()`(§2). `register_parser`/`register_post_processor`([parser-registry.md](parser-registry.md) §2.3)를 호출해 `.pdf` 교체, 이미지 확장자 등록(§6), 후처리 등록을 한 곳에서 수행 |
| `pipeline/utils/` | `vlm.py` 신규 — `caption_image(image_bytes, prompt) -> str` 순수 함수(`get_settings()` 기반 지연 클라이언트 생성, `embed.py`의 `build_embed_model()`과 동일 패턴) + `VLMCaptionReader`(`BaseReader` 상속, `load_data()`에서 이미지를 읽어 `caption_image()` 호출 후 `ImageDocument` 반환 — case B 전용, §2/§10) + `caption_embedded_images`(case A 공통 후처리 함수, `pipeline/plugins/image_ocr.py`가 `register_post_processor`로 등록). `ocr.py` 신규 — `extract_text(image_bytes) -> str` 순수 함수, PaddleOCR 래퍼(`get_settings()` 기반). `lang.py` 신규 — `detect_language(text) -> str` 순수 함수(`langdetect` 래퍼, ISO 639-1 반환), `build_caption_prompt(language) -> str`(§3.2) |
| `pyproject.toml` | `langdetect` 의존성 추가 |
| `config/settings.py` | 신규 최상위 `ProviderSettings`(`name`/`ollama_url`/`openai_api_key`) 추가. 기존 `EmbeddingSettings`에서 `provider`/`ollama_url`/`openai_api_key`/`openai_model` 제거, `model` 하나만 남김(provider별 모델명은 값 교체로 관리). `ImageCaptioningSettings`(`model`/`temperature`/`default_language`/`max_images_per_doc`/`max_concurrent_tasks`), `PdfOcrFallbackSettings`(`enabled`/engine/language/min_chars_per_page) 중첩 모델 신규 추가. `OPENAI_API_KEY` 환경변수 수동 오버라이드(현재 `embedding.openai_api_key`로 주입, `config/settings.py` 226~227행)를 `provider.openai_api_key`로 재배선. **이 스키마 형태 자체는 US-41 이전과 동일하게 유지한다** — 등록 방식만 바뀌었을 뿐 설정 구조는 바뀌지 않는다 |
| `pipeline/step/embed.py` | `build_embed_model()`이 `settings.embedding.provider/ollama_url/openai_api_key` 대신 `settings.provider.name/ollama_url/openai_api_key` + `settings.embedding.model`을 읽도록 변경 (query-side에서도 동일 함수를 `rag/retriever.py`가 재사용하므로 시그니처 변경 없이 내부 참조만 수정) |
| `settings.yaml`, `docker/settings.yaml`, `k8s/manifests/llm/rag-api/kustomize/overlays/dev/configmaps/settings.yaml` | 최상위 `provider` 블록 신규, `embedding` 블록에서 `provider`/`ollama_url`/`openai_api_key`/`openai_model` 제거, `ingestion.image_captioning`/`ingestion.pdf_ocr_fallback` 블록 추가(기존 스키마 그대로), `ingestion.parser_plugins`에 `"rag_api.pipeline.plugins.image_ocr:register"` 추가 — 세 파일 모두 반영 필요(누락 시 배포 환경 불일치, `parser_plugins` 누락 시 이 기능 자체가 조용히 비활성) |
| `tests/unit/test_settings.py` | `embedding.openai_api_key` 관련 fixture/assertion을 `provider.openai_api_key`로 이전 |
| `tests/unit/test_image_ocr_plugin.py` | 신규(구 계획의 `test_parse.py` 확장 대신 플러그인 전용 파일로 분리 — `parse.py` 자체는 무변경이므로). vision 모델 mock 기반 캡셔닝 테스트(언어별 프롬프트 분기 포함), OCR 엔진 mock 기반 폴백 테스트(전역 `enabled` on/off × 글자 수 충분/부족 조합), 두 기능 모두 `enabled: false` 기본값에서 `register()`가 아무 것도 등록하지 않음을 확인, `parser_plugins`에 이 모듈을 넣었을 때 `pipeline.step.parser.get_parsers()`/`get_post_processors()`에 반영되는지 확인 |
| `tests/unit/test_lang.py` | `detect_language()` 한국어/영어 판별 테스트 |
| `docs/internal/requirement/prd.md` | 구현 완료 시 §2 "지원 파일 형식"에 이미지 확장자 추가 |

## 8. 주의사항

- `enabled: false` 기본값으로 명시적 활성화 전까지 기존 동작을 완전히 유지한다 (하드룰 위반 없음 —
  `get_settings()` 단일 소스 유지).
- vision 모델 호출은 이미지/페이지별로 발생하므로 `max_images_per_doc`, `max_concurrent_tasks`로
  지연 폭증을 막는다. 로컬 8B 이하 모델이라도 문서당 이미지가 수십 개면 누적 지연이 커진다.
  비정보성 이미지를 먼저 걸러내는 안(2단계 필터)도 검토했으나 결정을 보류했다 — §9.
- 하위 Op(`chunk`/`embed`/`upsert`)은 수정 불필요 — 캡션 Document는 일반 텍스트 Document와 동일한
  인터페이스로 흐른다.
- **환각 리스크(실측 확인, 이미지 캡셔닝에만 해당)** — §3.1의 합성 이미지 테스트에서는 수치·텍스트를
  정확히 추출했지만, 각도·겹침·가림이 있는 실사진에서는 명백한 환각이 관찰됨(존재하지 않는 "두 번째
  고양이", "나비타이"를 서술, 없는 한글 텍스트를 있다고 단정). 문서 내 임베디드 이미지(case A)는
  대부분 디지털로 렌더링된 차트/스크린샷이라 리스크가 낮지만, 순수 이미지 업로드(case B)는 이
  리스크에 그대로 노출된다. **PDF OCR 폴백은 이 리스크에서 제외된다** — PaddleOCR은 인식 기반 엔진이라
  존재하지 않는 내용을 생성하지 않는다(오인식으로 틀린 문자를 낼 수는 있지만, 없는 문장을 지어내지는
  않는다). 이게 OCR 폴백을 VLM에서 분리한 핵심 이유다(§1).
- **재현성 문제(실측 확인, 이미지 캡셔닝에만 해당)** — 같은 이미지·유사한 프롬프트를 여러 번 호출했을
  때 날짜 같은 세부 수치 필드가 실행마다 다르게 환각되는 것을 확인함(예: "19 July 2024" vs "6 July
  2015" vs "352 days as of 19." — 셋 다 실제 원문과 다름). 캡션은 인제스트 시점에 한 번 생성되어
  영구 저장되므로, "어느 실행에서 어떤 값이 나왔는지"가 우연에 좌우되면 안 된다. 완화책:
  - `temperature`를 낮게 고정(기본 0.1)해 샘플링 변동성을 줄인다(§5) — 완전한 결정성은 보장 못함.
  - 캡션 Document의 metadata에 `source: "vlm_generated"` 플래그를 남겨, 검증되지 않은 생성 텍스트임을
    검색 결과 단계에서 구분할 수 있게 한다.
  - 수치·날짜처럼 정밀도가 중요한 필드에 크게 의존하는 문서(계약서, 인증서류 등)에는 이 기능을
    기본값(`enabled: false`)으로 두고 신중히 opt-in하도록 안내한다.
  - PaddleOCR은 동일 입력에 대해 결정적(deterministic)이라 이 문제 자체가 없다 — OCR 폴백을 별도
    엔진으로 분리한 두 번째 이유.

## 9. 보류된 의사결정

기각도 채택도 아니고, **판단에 필요한 데이터가 아직 없어 미룬** 항목만 담는다. 검토한 대안(§10)과
다른 점은 "이유가 있어 안 한다"가 아니라 "지금은 판단할 근거가 없다"는 것 — 재검토 조건을 명시해
다음에 같은 논의를 처음부터 반복하지 않게 한다.

### 이미지 캡셔닝 2단계 필터 (비정보성 이미지 사전 판별)

- **질문**: 로고/아이콘처럼 캡션이 필요 없는 이미지를 저비용으로 먼저 걸러내는 단계를 추가할지.
- **왜 지금 결정하지 않는가**: 이 판단에 필요한 데이터 두 가지가 모두 없다 — (1) 실제 코퍼스에서
  임베디드 이미지 중 정보성/비정보성 비율, (2) 판별 전용 소형 모델(예: moondream2)의 실측 성능
  (§3.1은 qwen2.5vl만 측정함). 이 둘 없이는 아래 두 안 중 무엇이 더 나은지, 애초에 필터링이
  순이득인지조차 알 수 없다.
- **후보안**:
  - **A. qwen2.5vl 재사용** — 같은 모델로 짧은 판별 호출 후 정보성 이미지만 전체 캡셔닝. 새 모델
    의존성은 없지만, 정보성 이미지 비율이 높은 문서에서는 판별 호출이 순수 오버헤드가 되어 필터
    없이 바로 캡셔닝하는 것보다 총 호출이 늘어날 수 있다.
  - **B. 전용 소형 모델(moondream2 등) 추가** — 판별 전용으로는 더 빠르고 저렴할 가능성이 높지만,
    provider 설정과 무관하게 별도 모델 의존성이 추가된다 — 모델 가짓수를 늘리지 않는다는 원칙과
    상충한다.
  - **C. 없음 (현재 채택)** — 모든 임베디드 이미지를 그대로 캡셔닝. 로고/아이콘이 많은 문서는
    지연·비용·검색 노이즈 손실을 감내한다. `max_images_per_doc`/`max_concurrent_tasks`가 최악의
    경우 지연 상한은 보장한다.
- **재검토 조건**: 이 기능 배포 후 실제 인제스트 로그에서 (a) 문서당 평균 임베디드 이미지 수,
  (b) 그중 캡션이 검색 결과 품질에 기여하지 않는 것으로 보이는 비율이 유의미하게 확인되면, 그
  데이터를 근거로 A/B 중 선택해 별도 backlog로 진행한다. 데이터 없이 미리 구현하지 않는다.

## 10. 검토한 대안

당장 재현될 수 있는 실수(다시 시도하면 실제로 문제가 나는 것)만 남긴다 — 단순 비교·기각 이력은
기록하지 않는다.

- **캡셔닝·OCR 모두 VLM 하나로 처리**: 실측(§3.1)에서 확인된 환각·비재현성이 스캔 PDF 본문
  텍스트에 그대로 노출된다 — 전사는 PaddleOCR, 설명은 VLM으로 분리해 이 리스크를 구조적으로
  없앤다(§8).
- **문서 단위 수동 강제 지정(`parser_strategy` 류)**: 배타적 "교체" 구조라 텍스트가 정상인
  문서에 잘못 켜면 원본을 깨진 OCR 결과로 덮어쓰는 사고 위험이 있어 자동 판단만 채택한다(§2).
- **case B 리더로 `llama-index-readers-file` 번들 리더 재사용**: 모델이 하드코딩돼 있고
  (`ImageReader`=pytesseract, `ImageCaptionReader`=Donut, `ImageVisionLLMReader`=BLIP-2)
  `parser_config`에 임의 콜백을 꽂을 훅이 없어 `caption_image()`를 끼워 넣을 여지가 없다 —
  `caption_image()`를 호출하는 얇은 커스텀 `VLMCaptionReader`를 새로 만든다(§2/§6).

## 11. 비범위

- **문서 내 언어 혼용** — §3.2의 언어 판별은 문서 전체가 단일 언어라고 가정한다. 한 문서 안에 여러
  언어가 섞인 경우(예: 영문 논문에 한글 각주) 세밀하게 문단·이미지 단위로 언어를 나누어 판별하지
  않는다 — 문서 전체 텍스트 기준 판별 결과를 그대로 쓴다.
- **HTML/MD/HWP 임베디드 이미지 추출** — case A는 PDF·DOCX만 지원한다(§1, §2). 이유는 현재 리더로
  바로 가능한 포맷만 우선 구현하기 위해서다:
  - HTML: 현재 `HTMLCleanReader`(trafilatura)는 본문 텍스트만 정제 추출하며 이미지를 버린다. 원본
    HTML의 `<img>` 태그를 별도로 재파싱해야 하는데 이 로직이 없다.
  - MD: 마크다운 이미지는 `![alt](path)` 참조 문법이라 임베디드 바이너리가 아니다. 로컬 파일/외부
    URL/base64 data URI 파싱이 필요한데 `MarkdownReader`엔 없다.
  - HWP: `llama-index-readers-hwp`(`base.py`) 확인 결과 텍스트 추출 메서드뿐이고 이미지(`BinData`)
    처리가 없다. HWP는 바이너리 컴파운드 포맷이라 이미지 추출은 완전히 새 파싱이 필요하다.
  - 실제 수요가 확인되면 포맷별로 별도 design 문서에서 다룬다.
- 멀티모달 벡터 검색 (§4의 B안)
- 페이지 단위 자동 판단 (한 문서 안에 텍스트 페이지와 스캔 페이지가 섞인 혼합 케이스) — 문서 단위
  평균 글자 수로만 판단한다(§2). 실제 혼합 문서 유스케이스가 확인되면 후속 과제.
- 문서/KB 단위 수동 강제 지정 API — `settings.yaml` 전역 opt-in 외의 오버라이드 경로는 두지 않는다(§10).
- 오디오/비디오 트랜스크립션
- 이미지 파일 자체에 대한 dedup(중복 이미지 감지) — 기존 dedup 파이프라인은 텍스트 기반(SimHash/
  MinHash)이라 캡션 텍스트에는 자동 적용되지만, 픽셀 단위 이미지 중복 감지는 다루지 않는다.
