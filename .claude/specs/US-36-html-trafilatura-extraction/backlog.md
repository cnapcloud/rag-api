---
id: US-36
title: HTMLCleanReader를 trafilatura 밀도 기반 추출로 교체
status: done
---

# US-36: HTMLCleanReader를 trafilatura 밀도 기반 추출로 교체

> 설계: [html-extraction.md](../../../docs/internal/design/html-extraction.md) 3절

## 목적

`HTMLCleanReader`(`pipeline/ops/parse.py`)의 태그 이름 deny-list(`nav`/`footer`/`header`/
`script`/`style`/`aside` 제거) 방식을 trafilatura의 텍스트/링크 밀도 기반 추출로 교체한다.
사이트마다 마크업 구조가 달라 태그 이름만으로는 boilerplate를 안정적으로 걸러낼 수 없고, 이
품질이 SimHash(dedup stage 1) 입력에 직접 영향을 준다.

## 범위

- `HTMLCleanReader.load_data()` 내부 구현을 trafilatura 호출로 교체
  - `trafilatura.extract(html, favor_precision=True, output_format="markdown", include_tables=True)`
  - `None` 반환 시 빈 문자열로 폴백 (예외 처리 불필요 — `validate_op`의 `min_content_chars`가 자연히 필터링)
- `BaseReader` 상속, `load_data(file, extra_info) -> list[Document]` 시그니처, 클래스명, `_get_file_extractor()`의
  `.html`/`.htm` 매핑 모두 변경 없음 (인터페이스 유지 원칙)
- 기존 `_STRIP_TAGS`, `_WS_RUN_RE`, `_NEWLINE_RUN_RE`, `_normalize_whitespace()` 등 BeautifulSoup 기반
  헬퍼 제거 (trafilatura가 공백/개행 정규화까지 포함하므로 후처리 불필요)
- `tests/unit/test_parse_html.py` 전면 재작성 — 기존 테스트는 BeautifulSoup 태그 제거 동작을 직접
  검증하므로 trafilatura 기준으로 다시 작성 필요 (마크다운 출력 포맷 검증 포함: 헤딩 `#`, 리스트 `-` 보존 등)

## 비범위

- 사이트 단위 반복 boilerplate 탐지 — 검토 후 폐기 (스트리밍 ingestion과 cold-start 비호환,
  `docs/internal/design/html-extraction.md` 2절 "검토 후 폐기한 대안" 참고)
- JS 렌더링 SPA 예외 처리(Playwright fallback) — pending, 백로그 없음
  (`docs/internal/design/html-extraction.md` 4절 참고)
- 마크다운 인식 청킹(`MarkdownNodeParser` 등) — chunk_op은 기존 `SentenceSplitter`(recursive)
  그대로 사용, 이번 US 범위 아님

## 완료 기준

- [x] `HTMLCleanReader.load_data()`가 trafilatura로 본문을 추출하고 `output_format="markdown"`
      결과를 반환함
- [x] `favor_precision=True`가 적용됨 (애매한 블록 제외)
- [x] `trafilatura.extract()`가 `None`을 반환하는 케이스에서 예외 없이 빈 문자열 `Document`를 반환함
- [x] `HTMLCleanReader` 클래스 인터페이스(시그니처, `_get_file_extractor()` 등록)가 변경되지 않아
      Dagster op 래퍼/`runner.py` 수정이 불필요함을 확인
- [x] `test_parse_html.py` 신규 테스트 전체 통과 (nav/footer 등 boilerplate 제거 확인은 trafilatura
      밀도 기반 판정으로 대체 검증, markdown 헤딩/리스트 보존 검증 추가)
- [x] 기존 WebConnector/ConfluenceConnector가 stage한 HTML 문서 인제스트 회귀 없음 (연관 테스트 통과,
      `tests/unit/` 390 passed / 1 skipped)

## 오픈 이슈

- `favor_precision=True`로 인한 본문 일부 손실 허용 범위 — 운영 데이터 재검증 필요
  (`docs/internal/design/html-extraction.md` 7절)
