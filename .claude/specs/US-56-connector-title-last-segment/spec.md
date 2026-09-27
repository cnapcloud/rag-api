# US-56: GitHub/Web 커넥터 title 결정 방식 변경

> 담당: `analyst` · spec 워크플로우 1단계 · 템플릿: `.claude/templates/spec.md`
> 상태는 `.claude/specs/index.md`에서만 관리한다(이 파일엔 별도 상태 필드를 두지 않는다).

## 요청 원문

GitHub/Web 커넥터 title 결정 방식 변경.

- GitHub 커넥터: title을 전체 경로(예: `src/rag_api/connectors/github.py`) 대신 마지막 path 세그먼트(파일명, 예: `github.py`)로 변경. 대상: src/rag_api/connectors/github.py (title=path로 되어 있는 create_doc/set_staged 호출부, 대략 217번/255번 라인 부근).
- Web 커넥터: title 추출 우선순위를 현재의 `og:title -> article h1 -> h1 -> <title> -> URL 전체(fallback)` 에서 `og:title -> <title> -> 마지막 path 세그먼트(fallback)` 로 변경. `article h1`/`h1` 셀렉터 단계를 완전히 제거하고, 최종 fallback도 URL 전체 문자열 대신 URL의 마지막 path 세그먼트로 바꾼다. 대상: src/rag_api/connectors/web.py의 `_extract_title` 함수(대략 76-107번 라인).
- Confluence 커넥터: 변경하지 않는다 — 현재처럼 Confluence API가 제공하는 page["title"]을 그대로 사용해야 한다 (path 기반으로 바꾸지 않는다는 점을 spec에 명시할 것).

배경: 사용자와 논의한 결과, GitHub는 source 필드에 이미 전체 경로가 남아있어 title은 파일명만으로 충분하다고 판단했고, Confluence는 이미 API가 사람이 지정한 제목을 주므로 path 기반으로 바꾸면 오히려 나빠진다(webui 링크가 없을 때 마지막 세그먼트가 숫자 ID가 될 수 있음)고 판단해 현행 유지로 결론냈다. Web은 article h1/h1 셀렉터가 사이드바나 관련 글 목록 등 엉뚱한 요소를 잘못 집어오는 경우가 있어 제거하기로 했고, <title> 태그는 신뢰도가 높아 유지하기로 했다.

이 내용을 바탕으로 spec.md를 작성해줘. 완료 기준(AC)에는 각 커넥터(GitHub/Web)별로 구체적인 입력-출력 예시가 포함되어야 하고, Confluence는 "변경하지 않음"이 명시적인 AC로 들어가야 한다(회귀 방지 목적).

## 목적

GitHub/Web 문서의 title이 전체 경로/부적절한 요소로부터 파생되어 사용자에게 가독성이
낮거나(GitHub: 전체 경로 노출) 부정확한 값이 표시될 수 있다(Web: h1 오탐). title을 각
소스 특성에 맞는 더 신뢰할 수 있는 값으로 산출해 가독성과 정확성을 높인다.

## 세부 기능 및 완료 기준

### F1. GitHub 커넥터 title을 파일명(마지막 path 세그먼트)으로 변경

문서 생성/스테이징 시 title에 전체 경로 대신 파일명만 사용한다.

- [x] **F1-1**: path가 `src/rag_api/connectors/github.py`인 파일을 신규 인제스트하면
  생성된 문서의 title이 `github.py`이다 (전체 경로 문자열이 아니다).
- [x] **F1-2**: path에 디렉터리 구분이 없는 루트 파일(예: `README.md`)을 인제스트하면
  title이 `README.md`이다 (마지막 세그먼트와 원래 path가 동일한 경우도 정상 동작).
- [x] **F1-3**: 기존 문서가 변경되어 재스테이징되는 경우에도(최초 생성이 아닌 갱신
  경로) title이 마지막 path 세그먼트로 설정된다.
- [x] **F1-4**: 문서의 source(source_uri) 필드는 이 변경과 무관하게 기존과 동일하게
  전체 경로를 포함한 값을 유지한다.

### F2. Web 커넥터 title 추출 우선순위 변경

title 추출 시 `article h1`/`h1` 셀렉터 단계를 제거하고, 최종 fallback을 URL 마지막
path 세그먼트로 바꾼다.

- [x] **F2-1**: HTML에 `<meta property="og:title" content="예시 제목">`이 있으면
  `<title>` 태그나 h1 요소 존재 여부와 무관하게 title은 `예시 제목`이다.
- [x] **F2-2**: HTML에 og:title이 없고 `<title>페이지 타이틀</title>`만 있으면(본문에
  `<article><h1>다른 텍스트</h1></article>`가 있어도) title은 `페이지 타이틀`이다 —
  h1/article h1이 더 이상 title로 채택되지 않는다.
- [x] **F2-3**: HTML에 og:title도 `<title>` 태그(또는 그 텍스트)도 없으면, 예를 들어
  URL이 `https://example.com/docs/getting-started`인 경우 title은 URL 전체 문자열이
  아닌 `getting-started`이다.
- [x] **F2-4**: og:title/`<title>` 모두 없고 URL이 trailing slash로 끝나는 경우(예:
  `https://example.com/docs/`)에도 fallback 처리 결과가 빈 문자열이 되지 않는다(수동
  확인: 사람이 식별 가능한 값이 title로 채택됨을 확인).

### F3. Confluence 커넥터 title 로직 변경 없음 (회귀 방지)

Confluence는 API가 제공하는 page title을 그대로 사용하는 기존 동작을 유지한다.

- [x] **F3-1**: Confluence 페이지를 인제스트하면 문서 title이 Confluence API 응답의
  `page["title"]` 값과 동일하다 — path/URL 마지막 세그먼트 기반 값으로 대체되지 않는다.
- [x] **F3-2**: Confluence 관련 기존 테스트(title 산출 관련)가 이번 변경 이후에도
  수정 없이 그대로 통과한다.

### 공통 완료 기준

- [x] **C1**: GitHub/Web/Confluence 커넥터 관련 테스트 전체 통과.

## 비범위

- Web 커넥터가 og:title/`<title>` 외의 다른 메타데이터(예: JSON-LD, twitter:title)를
  추가로 참조하도록 확장하는 것은 이번 범위에 포함하지 않는다. 필요해지면 별도 US로
  분리한다.
- GitHub 커넥터에서 파일명 충돌(동일 파일명, 다른 디렉터리) 시 title을 구분하기 위한
  추가 표시(예: 상위 디렉터리 포함)는 이번 범위에 포함하지 않는다.
- Confluence 커넥터의 title 로직 자체를 개선하는 작업(예: webui 링크 폴백 방식 변경)은
  이번 범위에 포함하지 않는다 — 현행 유지만 확인한다.

## 의존성

- 없음

## 오픈 이슈 (선택)

- (없음)

## 승인

- [x] 사용자 승인 완료
