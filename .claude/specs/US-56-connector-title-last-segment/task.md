# US-56: GitHub/Web 커넥터 title 결정 방식 변경 — Task 분리 및 구현 방법

> 담당: `designer` · spec 워크플로우 2단계 산출물(3단계 implementer 입력) · 템플릿:
> `.claude/templates/task.md`

**대상**: [design.md](design.md)

## Task 목록

| Task | 제목 | 대상 완료 기준 (AC) | 관련 파일 | 의존 |
|---|---|---|---|---|
| T1 | GitHub title을 파일명으로 변경 | F1-1, F1-2, F1-3, F1-4 | `src/rag_api/connectors/github.py`, `tests/unit/test_github_connector.py` | 없음 |
| T2 | Web title 추출 우선순위 변경 | F2-1, F2-2, F2-3, F2-4 | `src/rag_api/connectors/web.py`, `tests/unit/test_web_connector.py` | 없음 |
| T3 | Confluence 회귀 확인 + 전체 테스트 통과 | F3-1, F3-2, C1 | `src/rag_api/connectors/confluence.py`(읽기 전용 확인), `tests/unit/test_confluence_connector.py`, `tests/unit/test_github_connector.py`, `tests/unit/test_web_connector.py` | 없음(T1/T2 완료 후 실행 권장이나 코드 의존은 없음) |

## 완료 기준 커버리지

| 완료 기준 (AC) | 담당 Task |
|---|---|
| F1-1 | T1 |
| F1-2 | T1 |
| F1-3 | T1 |
| F1-4 | T1 |
| F2-1 | T2 |
| F2-2 | T2 |
| F2-3 | T2 |
| F2-4 | T2 |
| F3-1 | T3 |
| F3-2 | T3 |
| C1 | T3 |

## T1. GitHub title을 파일명으로 변경

**대상 완료 기준**: F1-1, F1-2, F1-3, F1-4
**의존**: 없음
**관련 파일**:
- (수정) `src/rag_api/connectors/github.py`
- (수정) `tests/unit/test_github_connector.py`

구현 방법:
1. `src/rag_api/connectors/github.py`의 217번 라인 부근 `create_doc(... title=path, ...)`를
   `create_doc(... title=Path(path).name, ...)`로 변경한다. `Path`는 파일 상단(8번 라인)에
   이미 import되어 있으므로 추가 import 불필요.
2. 같은 파일 255번 라인 `set_staged(doc_id, title=path, ...)`도 동일하게
   `set_staged(doc_id, title=Path(path).name, ...)`로 변경한다 — 이 경로가 F1-3(갱신
   경로)에 대응한다.
3. `source=source_uri` (217번 라인 바로 위, 191-193번 라인에서 계산된 전체 경로 포함
   URL)는 그대로 둔다 — F1-4는 이 값이 변경되지 않았음을 확인하는 것이므로 코드
   수정이 아니라 테스트로 검증한다.
4. `Path("src/rag_api/connectors/github.py").name`은 `"github.py"`(F1-1), `Path("README.md").name`은
   `"README.md"`(F1-2, 디렉터리 구분 없는 루트 파일도 정상 동작 — `pathlib`가 알아서
   처리하므로 별도 분기 불필요)이다.
5. `tests/unit/test_github_connector.py`에서 `title` assertion이 있는 기존 테스트(56번
   라인 `"title": _FILE_PATH` 등 fixture/assert 지점)를 확인해, 신규 생성 경로 —
   F1-1 대응 —, 루트 파일 경로 — F1-2 대응 —, 재스테이징(갱신) 경로 — F1-3 대응 —, 그리고
   `source`/`source_uri`는 여전히 전체 경로임 — F1-4 대응 — 을 각각 검증하는 케이스로
   갱신하거나 신규 추가한다. 기존에 `title == 전체 경로`를 기대하던 assertion은 모두
   `Path(path).name` 기준으로 고친다.

## T2. Web title 추출 우선순위 변경

**대상 완료 기준**: F2-1, F2-2, F2-3, F2-4
**의존**: 없음
**관련 파일**:
- (수정) `src/rag_api/connectors/web.py`
- (수정) `tests/unit/test_web_connector.py`

구현 방법:
1. `src/rag_api/connectors/web.py`에 `_extract_title` 함수(76-107번 라인) 바로 위에
   신규 헬퍼 `_url_last_segment(url: str) -> str`을 추가한다:
   - `urllib.parse.urlparse`(이미 12번 라인에서 import됨)로 path를 분리하고,
     `"/"`로 split한 뒤 빈 문자열이 아닌 세그먼트만 남겨 마지막 요소를 반환한다.
   - path에 비어있지 않은 세그먼트가 하나도 없으면(예: 루트 URL, trailing slash만
     있는 경우) `parsed.netloc`으로 폴백하고, `netloc`마저 비어있으면 원본 `url` 문자열
     그대로 반환한다 — F2-4(빈 문자열 금지) 대응.
   - 예: `"https://example.com/docs/getting-started"` → `"getting-started"`(F2-3),
     `"https://example.com/docs/"` → `"docs"`(F2-4).
2. `_extract_title` 함수의 docstring(77-79번 라인)을 새 우선순위
   `og:title -> <title> -> fallback`으로 갱신하고, 89-93번 라인(`article h1` 블록)과
   95-99번 라인(`h1` 블록)을 통째로 삭제한다. `og` 처리(85-87번 라인) 다음 바로
   `tag = soup.find("title")` 처리(101-103번 라인)로 이어지도록 한다. 함수 시그니처
   (`html: str, fallback: str`)와 마지막 `return fallback`(107번 라인)은 그대로 둔다.
3. 호출부 두 곳을 수정한다 — 364번 라인 `_extract_title(html, source_uri)`와 394번 라인
   `_extract_title(html, source_uri)`를 각각
   `_extract_title(html, _url_last_segment(source_uri))`로 바꾼다. 384번 라인
   (`create_doc(... title=source_uri, ...)`, 최초 생성 시 임시 title)은 393-394번 라인
   직후 `set_staged`가 `_extract_title` 결과로 덮어쓰므로 변경하지 않는다(design.md
   리스크 참고).
4. `tests/unit/test_web_connector.py`의 `_extract_title` 우선순위 테스트 블록(923번
   라인 이후)을 새 사양에 맞게 정리한다:
   - `test_og_title_wins`(928번 라인)는 유지하되, HTML에서 `article h1`/`h1`을 제거해도
     결과가 같음을 계속 검증한다(그대로 둬도 무방).
   - `test_article_h1_wins_over_h1`(939번 라인), `test_h1_wins_over_h1`(948번 라인),
     `test_empty_h1_falls_through_to_title`(983번 라인)은 삭제하거나, h1 관련 부분을
     제거하고 `og:title 없음 + <title> 있음` 케이스(F2-2)로 재작성한다 — 본문에
     `<article><h1>다른 텍스트</h1></article>`가 있어도 title이 `<title>` 값이 되는지
     검증하는 형태로 만든다.
   - `test_html_title_used_when_no_h1`(957번 라인)은 이름을 유지하거나
     `test_html_title_used_when_no_og`처럼 개명하고 그대로 통과하는지 확인한다(로직
     변경 없음).
   - 967번 라인 `_extract_title(html, "https://example.com/page")` 테스트는 fallback
     인자를 그대로 문자열로 전달하는 단위테스트이므로 함수 자체는 변경 없이 통과한다.
     이와 별도로 `_url_last_segment`에 대한 신규 단위테스트를 추가해
     `"https://example.com/docs/getting-started"` → `"getting-started"`(F2-3),
     `"https://example.com/docs/"` → `"docs"`(F2-4, trailing slash), 필요하면
     `"https://example.com/"` → 빈 문자열이 아님(netloc 폴백)까지 커버한다.
   - 74번/154번/201번/251번/351번/610번/648번/1016번/1062번 라인처럼
     `patch("rag_api.connectors.web._extract_title", return_value=...)`로 모킹된
     기존 흐름 테스트는 `_extract_title` 자체를 모킹하므로 우선순위 변경의 영향을
     받지 않는다 — 수정 불필요.

## T3. Confluence 회귀 확인 + 전체 테스트 통과

**대상 완료 기준**: F3-1, F3-2, C1
**의존**: 없음(코드 의존은 없으나, T1/T2가 만든 변경을 포함해 전체 스위트를 최종
확인하는 성격상 T1/T2 이후 실행하는 것을 권장)
**관련 파일**:
- (읽기 전용, 수정 금지) `src/rag_api/connectors/confluence.py`
- (읽기 전용, 수정 금지) `tests/unit/test_confluence_connector.py`
- (실행 확인) `tests/unit/test_github_connector.py`
- (실행 확인) `tests/unit/test_web_connector.py`

구현 방법:
1. `src/rag_api/connectors/confluence.py`에서 title이 여전히 `page["title"]`을 그대로
   사용하고 있는지(코드 미수정) 확인한다 — 이 task에서는 이 파일을 절대 수정하지
   않는다.
2. `tests/unit/test_confluence_connector.py`를 그대로 실행해 title 관련 기존 테스트가
   수정 없이 통과하는지 확인한다(F3-2). 만약 실패하면 T1/T2의 변경이 Confluence
   커넥터 코드에 실수로 영향을 준 것이므로 T1/T2 diff를 되짚어 confluence.py에 손댄
   부분이 없는지 확인한다(이 task 자체에서 confluence.py를 고치지 않는다).
3. F3-1은 별도 신규 테스트가 필요하면 `test_confluence_connector.py`에 "생성된 문서
   title이 `page["title"]`과 동일하고 path/URL 마지막 세그먼트 기반 값이 아님"을
   명시적으로 검증하는 케이스를 추가한다(기존 테스트가 이미 이를 충분히 커버하면
   생략 가능 — 실제 코드 확인 후 판단).
4. 마지막으로 GitHub/Web/Confluence 커넥터 관련 테스트 전체
   (`tests/unit/test_github_connector.py`, `tests/unit/test_web_connector.py`,
   `tests/unit/test_confluence_connector.py`)를 실행해 전부 통과하는지 확인한다(C1).
   design.md 리스크&롤백에서 식별한 회귀 위험(T1/T2에서 프로덕션 코드 및 공유
   테스트 fixture를 수정)이 여기 걸리므로, 이 task에서는 개별 테스트 파일 단위가
   아니라 세 파일 전체를 대상으로 확인한다.
