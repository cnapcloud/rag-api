# 파서 레지스트리(US-41) 도입 배경 — rag-api 공개 전제

design 문서([parser-registry.md](../../docs/internal/design/parser-registry.md))는 등록 메커니즘의
구조만 다루고, "왜 지금 이게 필요한가"의 실제 배경(비공개 파서 구현을 별도 저장소에서 주입해야
한다는 요구)은 의도적으로 담지 않았다 — 그 문서는 rag-api 일반 확장 아키텍처만 다루도록
범위를 좁혔기 때문이다. 여기 그 배경만 기록한다.

- rag-api는 **공개(오픈소스) 저장소**로 확정됨. 그래서 이미지 캡셔닝/OCR 폴백(US-40) 같은
  기능의 실제 구현(프롬프트, 모델 선택, 실험 근거 등 design 문서 내용 자체 포함)을 rag-api에
  두면 공개된다 — 코드뿐 아니라 그 기능의 design 문서도 마찬가지로 노출 대상이라는 점을 놓치기
  쉽다.
- 이런 기능은 rag-ent-api(비공개 enterprise 레이어) 쪽에 구현하고, rag-api는 확장 지점만
  제공해야 한다는 결론에 도달 — US-41 파서 레지스트리가 그 결과물.
- **2026-07-16 완료**: rag-ent-api 쪽 실제 배선을 완료함(E-21). `pipeline/plugins/image_ocr.py`
  가 유일한 진입점, `config/settings.py`의 `IngestionSettings(RagApiIngestionSettings)`
  서브클래스가 `image_captioning`/`pdf_ocr_fallback`을 갖는다. OCR 엔진은 계획했던 PaddleOCR
  대신 RapidOCR로 채택(설치 용량/정확도 실측 근거는 rag-ent-api
  `docs/internal/reference/02-ocr-engine-selection.md`). rag-api 쪽 US-40
  backlog/`image-ocr-parsing.md`는 이 작업으로 대체되어 삭제, 내용은 rag-ent-api의
  `E-21-image-captioning-ocr-fallback.md`/`docs/internal/design/05-image-ocr-parsing.md`로
  이관됨 — 앞으로 이 기능을 다시 조사할 때는 rag-api가 아니라 rag-ent-api 저장소를 볼 것.

**재발 방지 교훈**: "이 기능을 비공개로 유지해야 한다"는 요구가 나오면, 코드만 옮기면 되는 게
아니라 **그 기능을 설명하는 design 문서 자체도 공개 저장소에 남으면 안 된다**는 점을 함께
확인할 것 — design 문서가 코드보다 더 많은 "왜"와 실험 데이터를 담고 있어 정보 노출 폭이 더 클
수 있다.
