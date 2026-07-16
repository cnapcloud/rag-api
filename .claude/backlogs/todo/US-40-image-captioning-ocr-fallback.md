# US-40: 이미지 캡셔닝 + PDF OCR 폴백

**상태**: todo

> 설계: [image-ocr-parsing.md](../../../docs/internal/design/image-ocr-parsing.md)

## 목적

`parse_op`이 현재 이미지를 완전히 무시해 다이어그램·차트 중심 문서에서 핵심 정보가 유실되고,
텍스트 레이어가 없는 스캔 PDF는 빈 문서로 색인된다. 설계 문서(§1)에 정리된 두 기능으로 이를
보완한다. US-04(구, 삭제됨)를 대체 — 설계가 vision 모델 단일화에서 캡셔닝/OCR 엔진 분리 구조로
바뀌어 재작성했다.

## 범위

설계 문서(§2~§7)에 상세가 있으므로 여기서는 목록만 나열한다.

- 이미지 캡셔닝(설명, VLM `qwen2.5vl:3b`) — PDF·DOCX 임베디드 이미지(case A) + 순수 이미지 파일(case B)
- 캡션 언어 자동 판별(§3.2) — case A는 문서 텍스트 기반, case B는 `default_language` 설정값
- PDF OCR 폴백(전사, PaddleOCR) — 페이지 평균 글자 수 자동 판단 + 전역 opt-in(§2, §5)
- `pipeline/plugins/image_ocr.py` 신규 — [parser-registry.md](../../../docs/internal/design/parser-registry.md)
  (US-41)의 `register_parser`/`register_post_processor`로 `.pdf`를 `PyMuPDFOCRFallbackReader`로
  교체하고 이미지 확장자·후처리를 등록하는 `register()` 진입점(§2, §7). `pipeline/step/parse.py`는
  무변경 — `ingestion.parser_plugins`에 이 모듈 경로만 추가
- `settings.yaml`/`config/settings.py`에 `ingestion.image_captioning`, `ingestion.pdf_ocr_fallback`
  블록 추가(§5, §7)
- **기존 `embedding` provider 설정 리팩터링(§5, §7)** — `embedding.provider`/`ollama_url`/
  `openai_api_key`/`openai_model`을 신규 최상위 `provider`(`name`/`ollama_url`/`openai_api_key`)
  블록으로 이관, `embedding.model` 하나로 통합(provider 전환 시 값 직접 교체). `image_captioning`도
  같은 `provider` 블록을 공유. 이 리팩터링은 이번 US 범위이지 후속 과제가 아니다 — 새 기능
  추가 김에 기존 임베딩 설정 구조도 같이 정리하기로 결정(대화 내 확정).

  - `pipeline/step/embed.py`의 `build_embed_model()` 내부 참조 변경 (시그니처는 불변 —
    `rag/retriever.py`가 query 임베딩에 동일 함수를 재사용하므로 호출부 수정 없음)
  - `config/settings.py`의 `OPENAI_API_KEY` 환경변수 수동 오버라이드를
    `embedding.openai_api_key` → `provider.openai_api_key` 대상으로 재배선
  - `settings.yaml`, `docker/settings.yaml`,
    `k8s/manifests/llm/rag-api/kustomize/overlays/dev/configmaps/settings.yaml` 3곳 모두 반영
    (하나라도 누락 시 해당 배포 환경에서 임베딩 설정 로드 실패)

## 비범위

설계 문서 §10에 근거와 함께 정리되어 있다 — 요약만:

- HTML/MD/HWP 임베디드 이미지 추출 (리더별 재파싱 로직 부재, 후속 과제)
- 멀티모달 벡터 검색(CLIP 등), 오디오/비디오 트랜스크립션
- 페이지 단위 자동 판단(혼합 스캔 문서), 문서 내 언어 혼용 세분화
- 문서/KB 단위 수동 강제 지정 API (전역 opt-in만 지원)
- 이미지 파일 자체의 픽셀 단위 dedup

## 완료 기준

- [ ] `image_captioning.enabled: false`(기본값)에서 기존 파싱 결과가 완전히 동일함을 확인
- [ ] `image_captioning.enabled: true` — PDF/DOCX 임베디드 이미지가 캡션 Document(`metadata.type:
      "image_caption"`)로 추가되고, 언어 판별 결과에 맞는 프롬프트로 캡셔닝됨을 확인
- [ ] 순수 이미지 파일(case B) 업로드 시 `default_language`로 캡셔닝, `enabled: false`면
      `IngestValidationError` 발생 확인
- [ ] `pdf_ocr_fallback.enabled: false`(기본값)에서 스캔 PDF도 기존과 동일하게(빈 텍스트) 처리됨을 확인
- [ ] `pdf_ocr_fallback.enabled: true` — 글자 수 충분한 정상 PDF는 OCR 미실행, 미달 PDF만 PaddleOCR
      경로로 전환됨을 확인
- [ ] `max_images_per_doc`/`max_concurrent_tasks` 상한이 실제로 적용됨을 확인
- [ ] `provider` 블록 리팩터링 후 기존 임베딩 파이프라인(ingest 시 chunk 임베딩, retrieval 시 질의
      임베딩) 양쪽 모두 provider=ollama/openai 각각에서 정상 동작 확인 — 회귀 없음
- [ ] `settings.yaml`/`docker/settings.yaml`/k8s configmap 3곳 모두 새 스키마로 갱신, 어느 하나로
      실행해도 설정 로드 성공 확인
- [ ] 관련 테스트(`tests/unit/test_parse.py`, `tests/unit/test_lang.py`, `tests/unit/test_settings.py`,
      `tests/unit/test_embed.py`) 전체 통과

## 의존성

없음.

## 오픈 이슈

- `tests/conftest.py`의 `mock_dagster_resources` 픽스처가 `rag_api.defs.resources.resources`에서
  `EmbeddingResource`/`MinIOResource`/`QdrantResource`/`RedisResource`를 import하지만 해당
  모듈에는 `S3Resource`만 실존 — 이 픽스처는 어느 테스트에서도 참조되지 않는 죽은 코드로 보임.
  이번 US와 무관하지만 `provider`/`model` 네이밍이 겹쳐 혼동을 줄 수 있어 발견한 김에 기록.
  정리 여부는 별도 판단(이번 US 완료 기준에는 포함하지 않음).
