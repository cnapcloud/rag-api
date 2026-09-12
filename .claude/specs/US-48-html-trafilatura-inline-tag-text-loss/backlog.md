# US-48: trafilatura favor_recall 모드가 인라인 서식 태그 주변 텍스트를 유실하는 버그 수정

**상태**: done

## 목적

kb-01의 나무위키 "고양이" 문서에서, 원문 "사람 나이로 치면 약 150살이다."가 인제스트 후
"사람 나이로 치면 약"까지만 저장되고 "150살이다."가 통째로 사라지는 문제가 발견됐다. 원인은
rag-api 코드가 아니라 `parser/html.py`가 사용하는 서드파티 `trafilatura`(2.1.0, 현재 PyPI
최신)의 `favor_recall=True` 추출 모드가 `<strong>`처럼 인라인 서식 태그로 감싼 텍스트와 그
직후 텍스트 노드를 통째로 삼키는 버그였다(upstream `adbar/trafilatura` 이슈 #882, #890 —
2026-07-28 기준 아직 미배포 상태). `html_extraction_policy` 기본값이 `"lenient"`라 실제
운영에서는 항상 `favor_recall=True` 경로를 타므로 영향 범위가 넓다.

## 범위

- `parser/html.py`의 `HTMLCleanReader.load_data()`에서 HTML을 `trafilatura.extract()`에
  넘기기 전에 `<strong>`/`<b>`/`<em>`/`<i>` 인라인 서식 태그를 unwrap(태그만 제거, 텍스트는
  보존)하는 전처리(`_unwrap_inline_tags`)를 추가한다.
- 회귀 테스트 추가(`tests/unit/test_parse_html.py`) — unwrap 함수의 결정론적 동작(태그 제거,
  텍스트 보존)을 검증한다.

## 비범위

- `trafilatura` 라이브러리 자체 업그레이드/다운그레이드 — 확인 결과 최신 버전(2.1.0)에도
  미해결이며, 관련 fix(#882)는 아직 미배포 상태라 지금 시점엔 시도할 것이 없음. 향후 신규
  릴리스가 나오면 CHANGELOG에서 #882/#890 반영 여부만 재확인.
- 원본 trafilatura 버그를 최소 HTML로 결정론적으로 재현하는 통합 테스트 — 실제 재현이 namu.wiki
  페이지의 구체적 DOM 구조(Vue 렌더링 속성 등)에 의존해, 단순화한 HTML로는 재현되지 않음을
  확인했다. trafilatura 내부 동작에 의존하는 취약한 테스트를 추가하는 대신
  `_unwrap_inline_tags` 함수 자체만 결정론적으로 검증한다.
- 이미 인덱싱된 다른 web 커넥터 문서의 일괄 재인제스트 — kb-01의 web 커넥터 스케줄에 의해
  자연스럽게 재크롤되는 것을 확인했고(2026-07-28 06:59 dagster-run), 별도 수동 일괄 작업은
  하지 않음.

## 완료 기준

- [x] `_unwrap_inline_tags`가 `strong`/`b`/`em`/`i` 태그를 제거하면서 텍스트는 보존한다 —
      `tests/unit/test_parse_html.py` 신규 테스트 5개 포함 전체 14개 통과
- [x] 실제 나무위키 "고양이" 문서(`/Users/lemon/Downloads/4d394c3563844ce0.html`)를
      `HTMLCleanReader`로 직접 재파싱해 "코듀로이"/"150살이다" 텍스트가 온전히 보존됨을 확인
- [x] kb-01 재인제스트(2026-07-28 06:59 dagster-run) 후 Qdrant 실데이터(포인트
      `caecd75f-a566-4144-a0ca-35c753d58960`)에 "사람 나이로 치면 약 150살이다." 전체 문장이
      온전히 저장됨을 직접 조회로 확인
- [x] `/api/search`(hybrid, rerank) 쿼리 "코듀로이"가 해당 청크를 결과에 반환함을 UI에서 확인

## 의존성

없음 — US-36(trafilatura 밀도 기반 추출 도입)/US-39(lenient 기본값 전환) 이후 운영 중 발견된
회귀성 이슈.

## 오픈 이슈

- 굵게/기울임 강조 정보는 unwrap 과정에서 사라진다. 검색 파이프라인이 강조 서식을 사용하지
  않아 현재는 트레이드오프로 수용.
- unwrap 대상은 `strong`/`b`/`em`/`i` 4종으로 한정했다. trafilatura #890은 인라인 태그가 2개
  이상 + table 조상 조합에서도 발생한다고 보고되어, 추후 다른 인라인 태그(`span`, `mark` 등)에서
  유사 증상이 재발하면 `_INLINE_TAGS_TO_UNWRAP` 목록 확장을 검토한다.
