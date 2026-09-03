---
name: pptx-page-label-type-pitfall
description: 서드파티 llama-index 리더(PptxReader 등)가 page_label에 int를 넣어 str 스키마 계약을 깨는 함정 + 다중 KB 검색에서만 드러나는 이유
metadata:
  type: project
---

`.pptx`(및 서드파티 리더를 쓰는 다른 확장자)를 파싱할 때, 우리 스키마가 강제하는
`page_label: str | None` 계약을 리더 자체가 지켜주지 않을 수 있다.

**원인**: `.pdf`는 자체 구현 `PyMuPDFReader`([pdf.py](../../src/rag_api/pipeline/steps/parser/pdf.py))를
쓰므로 `page.get_label()`이 항상 str을 반환하지만, `.pptx`는 llama-index 서드파티 `PptxReader`
(`llama_index/readers/file/slides/base.py`)를 그대로 쓰고, 이 리더는 슬라이드 순번을
`metadata["page_label"] = i`(int)로 채워 넣는다 — PDF `/PageLabels`와 무관한 라이브러리 자체
관례라서, 리더별로 같은 키 이름 아래 의미와 타입이 다르게 들어올 수 있다.

**왜 다중 KB 검색에서만 터졌는지**: RRF 병합(`query/merger.py`)과 리랭커는 원래 벡터 점수가 아니라
각 KB 내 순위 및 상대 리랭크 점수로 최종 top_n을 다시 정한다. 문제의 청크가 KB 하나만 검색할 땐
top_n 밖이라 응답에 안 들어가지만, 여러 KB를 합쳐 후보 풀과 경쟁 상대가 달라지면 순위가 바뀌어
top_n 안에 들어올 수 있다 — 즉 "특정 KB 조합에서만 재현"되는 버그가 항상 병합 로직 자체의 결함은
아니고, 데이터 자체에 있던 타입 문제가 노출 임계값을 넘는 시점의 차이일 수 있다.

**교훈**: 리더가 서드파티(llama-index 기본 제공)인 확장자는 메타데이터 키 이름이 같아도 값의
의미·타입을 우리 스키마 기준으로 다시 검증/정규화해야 한다. `parse.py`에서 `reader.load_data()`
직후 한 번 정규화하는 지점을 만들어두면(현재 `page_label` 정규화가 그 예), 리더별로 분기하지
않고 한 곳에서 계약을 보장할 수 있다. 새 확장자를 서드파티 리더로 추가할 때는 그 리더가 채우는
메타데이터 키가 우리 스키마 필드와 이름이 겹치는지 먼저 확인할 것.

관련: [US-47](../backlogs/US-47-page-label-type-mismatch-500.md)
