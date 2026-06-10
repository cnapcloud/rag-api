# US-04 — 문서 이미지 캡셔닝 (parse_op vision 처리)

## 상태
todo

## 개요

PDF, Word 등 문서에 이미지가 포함된 경우, 현재 `parse_op`은 이를 무시한다.
이 항목은 `parse_op`에 LLM 기반 캡셔닝을 추가해 이미지 내용을 검색 가능한 텍스트로 변환한다.

## 배경

- `SimpleDirectoryReader`는 텍스트만 추출하며, 삽입된 이미지는 조용히 버려진다.
- 기술 보고서, 논문 등 다이어그램 중심 문서는 핵심 정보가 유실된다.
- vision 모델로 캡셔닝해 텍스트 `Document`로 변환하면, 이후 파이프라인은 변경 없이 그대로 동작한다.

## 설계

### parse_op 확장

```
PDF / Word / MD
    |
    v
SimpleDirectoryReader  (기존 — 텍스트 추출)
    |
    v
텍스트 Document 객체
    |
이미지 추출 단계 (신규)
    |  소스 파일에서 이미지 추출 (pdfminer / python-docx)
    v
이미지별 vision 모델 호출  (Ollama vision / OpenAI vision)
    |  프롬프트: "Describe this image concisely for search indexing."
    v
캡션 Document 객체
    |  metadata: { source, page, image_index, type: "image_caption" }
    v
Document 합류 (텍스트 + 캡션)
    |
    v
chunk_op → embed_op → upsert_op  (하위 Op 변경 없음)
```

### 설정

`settings.yaml`의 `ingestion` 아래 신규 항목:

```yaml
ingestion:
  image_captioning:
    enabled: false          # 기본 비활성화 (opt-in)
    provider: ollama        # ollama | openai
    model: llava            # vision 지원 모델
    max_images_per_doc: 20  # 대용량 스캔 PDF 대비 상한
```

### 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `src/pipeline/ops/parse.py` | 이미지 추출 + 캡셔닝 로직 추가 (`enabled` 플래그로 분기) |
| `src/config/settings.py` | `ImageCaptioningSettings` 중첩 모델 추가 |
| `settings.yaml` | `ingestion.image_captioning` 블록 추가 |
| `tests/unit/test_parse.py` | vision 모델 mock 테스트 추가 |

## 주의사항

- vision 모델 호출은 이미지별 동기 처리; 배치가 필요하면 추후 `asyncio.gather`로 전환.
- `max_images_per_doc`으로 페이지 수백 개짜리 스캔 PDF의 지연 폭증 방지.
- 캡션 Document는 메타데이터에 `type: "image_caption"`을 포함해 필터링에 활용 가능.
- `enabled: false` 기본값으로 명시적 활성화 전까지 기존 동작 완전 유지.
- 하위 Op(chunk, embed, upsert)은 수정 불필요.

## 검토한 대안

- **OCR만 사용**: 속도는 빠르지만 텍스트 없는 도표·사진은 여전히 누락.
- **멀티모달 임베딩 (CLIP)**: 텍스트 출력 없음 — BM25 sparse 인덱스와 호환 불가.
- **이미지 무시**: 현행 동작; 텍스트 전용 문서 코퍼스에서는 허용 가능.
