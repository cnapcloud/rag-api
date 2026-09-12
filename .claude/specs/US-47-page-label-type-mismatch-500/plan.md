# Plan 47: page_label 타입 불일치로 인한 500 에러 수정

> 대상: [US-47](../backlogs/US-47-page-label-type-mismatch-500.md)

## 변경 파일

### `src/rag_api/pipeline/steps/parse.py`

`reader.load_data()` 직후, `documents` 순회하며 `page_label`을 정규화:

```python
for doc in documents:
    label = doc.metadata.pop("page_label", None)
    if label is None:
        continue
    if isinstance(label, int) and doc.metadata.get("page_num") is None:
        doc.metadata["page_num"] = label
    else:
        doc.metadata["page_label"] = str(label)
```

- `page_num`이 비어있고 `page_label`이 int면(=사실상 물리 순번, 예: `PptxReader`의 슬라이드
  순번) `page_num`으로 옮긴다.
- 그 외의 경우(PDF의 실제 `/PageLabels` str 등)는 str로 캐스팅해 계약을 보장한다.
- 모든 리더(PDF 자체 구현/서드파티 공용) 공통 지점이라 리더별 분기가 필요 없다.

### `src/rag_api/rag/retriever.py`

`_node_to_result()`에서 Qdrant payload를 읽어올 때도 동일하게 방어:

```python
page_label=str(v) if (v := meta.get("page_label")) is not None else None,
```

이미 int로 저장된 기존 Qdrant 청크(kb-02의 pptx 문서)가 재인제스트되기 전까지도 API가 죽지
않도록 하는 안전망.

## 조사 과정에서 확인한 사실

- `.pdf`는 자체 구현 `PyMuPDFReader`([parser/pdf.py](../../src/rag_api/pipeline/steps/parser/pdf.py))를
  쓰고 `page.get_label()`이 항상 str을 반환하므로 원래 문제 없음.
- `.pptx`는 llama-index 서드파티 `PptxReader`(`llama_index/readers/file/slides/base.py`)를
  그대로 쓰는데, 이 리더가 `metadata["page_label"] = i`(int, 슬라이드 순번)를 채운다 — 우리
  스키마의 "PDF `/PageLabels`" 의미와 무관한 라이브러리 자체 관례.
- Qdrant는 payload를 스키마리스 JSON으로 저장하므로 컬렉션 차원에서 타입을 강제하지 않는다 —
  같은 필드에 str/int가 섞여 있어도 write 시점엔 에러가 안 나고, read 시점에 우리 Pydantic 모델이
  깨진다.
- kb-01 단독/kb-02 단독 검색으로는 재현되지 않고 kb-01+kb-02를 함께 검색할 때만 500이 난 이유:
  RRF 병합(`rag/merger.py`)과 리랭커가 원래 벡터 점수가 아니라 각 KB 내 순위·상대 리랭크 점수로
  최종 top_n을 다시 정하므로, 후보 풀/경쟁 상대가 KB 조합에 따라 달라지면 같은 청크라도 top_n
  포함 여부가 바뀐다. 문제의 청크는 kb-02 단독 검색에선 top_n 밖이었지만 kb-01과 합쳐 병합되는
  과정에서 top_n 안으로 들어왔다.
- 실제 원인 문서를 찾은 방법: `kubectl -n llm port-forward svc/qdrant`로 로컬 포트포워딩 후,
  Qdrant REST `points/scroll`에 `{"key":"page_label","range":{"gte":0}}` 필터를 걸어 값이
  numeric인 포인트만 조회 — kb-02에서 `F_1330_Narkhede_Kafka (1).pptx`(doc_id
  `3b478130a76742db`) 47개 청크가 걸림.

## 테스트

- `tests/unit/test_parse.py`, `test_parse_formats.py`, `test_parse_html.py`,
  `test_parser_registry.py` (52 passed)
- `tests/unit/test_search.py`, `test_reranker.py`, `test_mcp_tools.py` (31 passed)
- `ruff check` 통과

## 후속 조치 (미완)

kb-02의 `F_1330_Narkhede_Kafka (1).pptx` 문서 재인제스트 — 기존 47개 청크의 `page_num`을
채우기 위해 필요하나 이번 세션에서는 실행하지 않음.
