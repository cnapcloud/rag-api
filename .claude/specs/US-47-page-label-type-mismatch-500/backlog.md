# US-47: 다중 KB 검색 시 page_label 타입 불일치로 인한 500 에러 수정

**상태**: done

> 구현 상세: [plans/47-page-label-type-mismatch-500.md](../plans/47-page-label-type-mismatch-500.md)

## 목적

kb-01+kb-02를 함께 검색(hybrid, RRF 병합)할 때만 `/api/search`가 500을 반환하는 문제가 있었다.
원인은 kb-02에 있는 pptx 문서 청크의 `page_label` 메타데이터가 int로 저장돼 있었고, 이 값이
RRF 병합·리랭크로 순위가 바뀌면서 응답 top_n에 포함되는 순간 `SearchResultItem.page_label:
str | None` 검증에서 깨졌기 때문이다. kb-01/kb-02 단독 검색 시엔 이 청크가 top_n 밖이라 드러나지
않았다.

근본 원인은 `.pptx` 파싱에 쓰는 llama-index 서드파티 `PptxReader`가 슬라이드 순번을 `page_label`
키에 int로 채워 넣는데(우리 스키마의 "PDF `/PageLabels`" 의미와 무관), 우리 스키마는 이 필드가
항상 str이라고 가정하고 있었던 것.

## 범위

- 인제스트 파이프라인이 `page_label` 메타데이터의 타입을 항상 스키마 계약(`str | None`)에 맞게
  정규화하도록 한다.
- 물리 페이지 번호(`page_num`)가 비어있는데 `page_label`이 사실상 물리 순번(숫자)인 경우, 그
  값을 버리지 않고 `page_num`으로 채워 넣는다.
- 검색 결과 조립 경로도 동일 필드에 대해 방어적으로 타입을 보정해, 이미 잘못 저장된 기존 데이터가
  섞여 있어도 API가 죽지 않게 한다.

## 비범위

- Qdrant에 이미 저장된 다른 레거시 오타입 데이터 전수 스캔 — 이번엔 이번에 발견된 kb-02 pptx
  건만 대상. 필요해지면 별도 이슈로 분리.
- `page_label` 이외 메타데이터 필드(예: `chunk_index`, `total_chunks`)의 타입 검증 강화 — 이번
  스코프 아님.

## 완료 기준

- [x] 인제스트 파이프라인이 `page_label`을 항상 `str | None`으로 정규화한다 (물리 순번은
      `page_num`으로 이동) — 관련 테스트(`tests/unit/test_parse*.py` 등 52개) 통과
- [x] 검색 응답 조립 시 `page_label`을 방어적으로 str 캐스팅해 타입 불일치로 인한 500을 방지한다 —
      관련 테스트(`test_search.py`/`test_reranker.py`/`test_mcp_tools.py` 등 31개) 통과

## 의존성

없음 — US-46(`0ce5654` `page_num`/`page_label` 분리) 이후 드러난 회귀.

## 오픈 이슈

- kb-02의 `F_1330_Narkhede_Kafka (1).pptx`(doc_id=`3b478130a76742db`) 청크 47개는 이미 int로
  저장돼 있어 API는 더 이상 죽지 않지만, `page_num`은 비어있는 채로 남아있다. 정확한 `page_num`을
  채우려면 이 문서를 재인제스트해야 한다 — 사용자가 시점을 별도로 정해 진행하기로 함.
