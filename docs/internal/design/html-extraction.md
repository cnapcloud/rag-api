# HTML 본문 추출 재설계

> 요건: [prd.md §2](../requirement/prd.md#2-문서-인제스트) "본문 정제"

## 1. 개요

`parse_op`의 `HTMLCleanReader`(`src/rag_api/pipeline/ops/parse.py`)는 현재 태그 이름 기반
deny-list(`nav`, `footer`, `header`, `script`, `style`, `aside` 제거)로 본문을 추출한다. 이 방식은
사이트마다 마크업 구조가 달라 실제 boilerplate(2차 네비게이션, 쿠키 배너, "이 페이지가
도움이 되었나요?" 위젯 등)를 태그 이름만으로 걸러내지 못하는 경우가 많고, 반대로 `<aside>`
안에 실제 본문이 들어있는 사이트에서는 본문을 통째로 잘라내는 오탐도 발생한다. 이 결과가
그대로 SimHash 입력(`docs/internal/design/dedup.md` 3.1.2, character 3-gram)으로 들어가기
때문에, boilerplate 잔존/본문 손실은 dedup 오탐·누락으로 직결된다.

이 문서는 태그 deny-list를 텍스트/링크 밀도 기반 추출(trafilatura)로 교체한다. JS 렌더링이
필요한 SPA 케이스에 대한 보완책은 설계만 해두고 도입은 보류한다 — **4절은 pending, 현재 도입
계획 없음** (Playwright는 이미지 파일 크기 증가(+500~700MB)와 배포 복잡도 증가(별도 Dockerfile
variant, 브라우저 바이너리 관리)를 초래하는데, 이 비용을 정당화할 실제 SPA 비율은 아직
확인되지 않음, 4절 참고). 사이트 반복 boilerplate에 대한 corpus 통계 기반 자동 탐지는
검토했으나 스트리밍 ingestion 구조와 근본적으로 맞지 않아 채택하지 않았다 (2절 끝 "검토 후
폐기한 대안" 참고).

관련 기존 설계: `docs/internal/design/dedup.md`(SimHash 입력이 되는 본문 정규화 품질에 직접 의존).

---

## 2. 현재 구현의 한계

`HTMLCleanReader.load_data()`(현재 구현):

```python
for tag in soup.find_all(self._STRIP_TAGS):
    tag.decompose()
body = soup.find("body") or soup
text = body.get_text(separator="\n", strip=True)
```

| 한계 | 증상 |
|---|---|
| 태그 이름 deny-list | `<div class="site-nav">`처럼 시맨틱 태그를 안 쓰는 사이트는 그대로 통과 |
| 밀도 무시 | 링크만 잔뜩 있는 목록(카드 그리드, 관련 글 목록)도 본문으로 포함됨 |
| `get_text()` 평탄화 | 헤딩/리스트/코드블록 구조가 사라져 순수 텍스트로 뭉개짐 — 청킹 시 문단 경계 단서 손실 |
| 사이트 반복 boilerplate 미탐지 | "Feedback", "Was this page helpful?" 같이 페이지마다 반복되지만 특정 태그로 식별 안 되는 문구는 deny-list로 원천 차단 불가 |
| 정적 파싱 한계 | SPA(React/Vue 등, 초기 HTML에 콘텐츠가 없고 JS 실행 후 채워짐)는 애초에 body가 비어 있어 deny-list 여부와 무관하게 추출 실패 |

### 검토 후 폐기한 대안 — corpus 빈도 기반 사이트 boilerplate 자동 탐지

"같은 connector의 여러 문서를 가로질러 줄 단위 등장 빈도를 집계해, 일정 비율 이상 반복되는
줄을 boilerplate로 자동 판정"하는 방식을 초안에서 검토했으나 폐기했다.

**폐기 이유:** 이 방법은 본질적으로 "코퍼스가 이미 쌓여 있어야" 의미가 생기는 후행적 통계다.
이 시스템은 문서가 들어올 때마다 즉시 처리하는 상시 ingestion 구조이므로:

- 특정 connector(사이트)에서 처음 들어오는 문서 1~N개는 비교할 통계 자체가 없어 아무 필터도
  받지 못한다.
- "통계가 쌓이면 나중에 나아진다"는 상시 ingestion 파이프라인 입장에서는 문서마다 처리 결과가
  달라지는 예측 불가능한 동작이지, 받아들일 수 있는 설계가 아니다.
- 탐지 로직을 Dagster asset으로 비동기 분리해도 이 cold-start 문제 자체는 없어지지 않는다 —
  통계 계산 시점을 늦췄을 뿐, "처음 N개는 무방비"라는 구조적 한계는 그대로 남는다.
- 새 connector(새 도메인)를 붙일 때마다 이 cold-start가 매번 반복된다.

즉 corpus 통계 기반 탐지는 스트리밍 ingestion 구조에 자연스럽게 맞지 않는 방법이며, 억지로
비동기로 분리하는 것은 문제를 해결하는 게 아니라 설계가 지저분해지는 시점을 미루는 것에
불과하다고 판단해 채택하지 않는다.

**남는 격차:** 밀도 기반 추출(3절)로 걸러지지 않는, 본문 블록 안에 자연스럽게 섞인 짧은 반복
문구("Feedback", "Edit this page on GitHub" 등)는 이 문서의 설계로는 해결하지 못하는 열린
문제로 남는다. 필요해지면 통계적 자동 탐지가 아니라 connector 설정에 운영자가 직접 등록하는
결정적(deterministic) 문구/셀렉터 제외 목록 같은 방식을 검토해야 한다 — 코퍼스 크기와 무관하게
첫 문서부터 동일하게 동작하기 때문이다. 이번 설계 범위에는 포함하지 않는다 (6절 오픈 이슈 참고).

---

## 3. 설계 — 밀도 기반 추출 (trafilatura)

### 3.1 추출 알고리즘 교체

태그 이름 deny-list 대신 trafilatura의 텍스트/링크 밀도 기반 본문 추출로 교체한다.
trafilatura는 DOM 블록별 텍스트 길이 대비 링크 밀도, 태그 밀도, 문장 부호 비율 등을
종합해 "이 블록이 본문일 확률"을 스코어링하는 방식(readability류 알고리즘 계열)이라, 사이트별
마크업 관례(시맨틱 태그 사용 여부)에 의존하지 않는다.

`trafilatura`는 이미 `pyproject.toml`에 의존성으로 등록되어 있고(`connectors/web.py`의
`_has_sufficient_content()`가 콘텐츠 충분성 체크용으로 이미 사용 중), 실제 추출 결과를
`Document.text`로 쓰는 것은 이번이 처음이다.

### 3.2 추출 정책 — `strict` / `lenient` / `balanced` (US-39, 2026-07-13 갱신)

trafilatura는 `favor_precision`/`favor_recall` 두 boolean을 받지만, 내부적으로는
(`trafilatura/settings.py`) `"recall" if recall else "precision" if precision else "balanced"`
순서로 평가되는 3단계 tri-state다 — `favor_recall=True`를 주면 `favor_precision` 값은 아예
무시된다. 이 tri-state를 `settings.ingestion.html_extraction_policy`
(`Literal["strict","lenient","balanced"]`)로 그대로 노출한다.

**정책별 실제 동작 차이** (`trafilatura==2.1.0` 소스 확인, `htmlprocessing.py`/`main_extractor.py`)
— 세 정책은 "본문인지 애매한 블록을 얼마나 적극적으로 포함시키는가"라는 하나의 축 위에 있다:

| 정책 | 판단 기준 | 구체적 처리 |
|---|---|---|
| `strict` | 애매하면 제외 | `PRECISION_DISCARD_XPATH` 추가 삭제, heading/quote 요소도 링크 밀도 기준으로 추가 삭제, 문서 끝 trailing title 삭제, teaser(요약/미리보기) 블록 삭제 |
| `balanced` (기본, 미설정) | 표준 임계치 | teaser 블록만 표준 강도로 삭제, strict/lenient 전용 강화·완화 로직 미적용 — 필요시 외부 알고리즘(readability)과 비교해 더 나은 결과 채택 |
| `lenient` | 애매하면 포함 | teaser 블록 삭제 생략, 본문 후보 태그에 `div`/`lb`/`list` 추가 포함, 정리 후 `<p>` 요소가 하나도 안 남으면 정리 자체를 롤백, 추출 텍스트가 이미 충분히 길면(`min_extracted_size`의 10배 이상) 외부 알고리즘 비교 생략하고 그대로 확정 |

**기본값은 `lenient`** (최초 설계 당시엔 `favor_precision=True`, 즉 `strict`였으나 US-39에서 전환).

- 애초 `strict` 선택 근거: dedup SimHash는 "본문이 거의 동일한가"를 character 3-gram으로
  비교하므로, 애매한 블록이 문서마다 들쭉날쭉 포함/제외되면 동일 본문의 SimHash가 벌어져
  오탐이 늘어난다는 우려였다.
- 전환 계기: kb-02 doc_id=`b950892c61d1463c`(namu.wiki "고양이" 문서)에서 `strict` 정책이
  실제 본문의 90%+ (105KB 중 7.8KB만 남음)를 "애매한 블록"으로 오판해 통째로 버렸다 — 위키형
  페이지의 각주/목차/접기박스 밀집 구조가 이 정책의 "애매하면 지운다" 판정을 과도하게
  트리거한 사례. 본문 손실이 "드물게 일부"가 아니라 문서 대부분을 삼킬 수 있음이 실측으로
  확인되어, 3.2 하단에 있던 "운영 데이터로 재검증 필요" 오픈 이슈가 실제로 재검증된 결과다.
- `lenient`의 트레이드오프: 라이선스 푸터 같은 짧은 boilerplate가 본문에 섞여 들어올 수 있음
  (실측 확인됨). dedup SimHash 안정성에 대한 최초 우려는 이론적으로는 여전히 유효하지만,
  namu.wiki류 위키 페이지의 본문 손실 규모가 훨씬 크고 명확한 회귀였기 때문에 우선순위를
  바꿨다. `strict`/`balanced`가 필요한 배포는 `html_extraction_policy`만 바꾸면 된다
  (코드 변경 불필요).

### 3.3 출력 포맷을 markdown으로 변경

`get_text(separator="\n")` 평탄화 대신 trafilatura `output_format="markdown"`을 사용한다.
헤딩(`#`), 리스트(`-`/`1.`), 코드블록(\`\`\`)이 텍스트에 보존된다.

- 청킹 품질: 현재 `chunk_op`(`pipeline/ops/chunk.py`)은 HTML 문서도 다른 문서 타입과 동일하게
  `SentenceSplitter`(recursive 전략)로 분할한다. 마크다운 문법 자체를 인식하는 헤딩 경계 분할기는
  아님 — 하지만 마크다운 구문이 남아있으면 문장 경계가 더 명확해지고(리스트 항목이 줄바꿈으로
  분리됨), 사람이 청크를 검수할 때도 원문 구조를 파악하기 쉬워진다.
- 마크다운 인식 청킹(예: `MarkdownNodeParser`로 헤딩 단위 분할)은 이번 범위 밖 — 오픈 이슈로 남김.

### 3.4 `HTMLCleanReader` 인터페이스는 유지

`BaseReader` 상속, `load_data(file, extra_info) -> list[Document]` 시그니처, 클래스명 모두
그대로 유지한다. `_get_file_extractor()`에 등록된 `.html`/`.htm` 매핑도 변경 없음. 내부
구현(`load_data()` 본문)만 BeautifulSoup 태그 제거 로직에서 trafilatura 호출로 교체한다.

```python
class HTMLCleanReader(BaseReader):
    def load_data(self, file: Path, extra_info: dict | None = None) -> list[Document]:
        import trafilatura

        from rag_api.config.settings import get_settings

        with open(file, encoding="utf-8") as f:
            html = f.read()

        policy = get_settings().ingestion.html_extraction_policy
        text = trafilatura.extract(
            html,
            favor_precision=(policy == "strict"),
            favor_recall=(policy == "lenient"),
            output_format="markdown",
            include_tables=True,
        ) or ""

        metadata: dict = {"file_path": str(file)}
        metadata.update(extra_info or {})
        return [Document(text=text, metadata=metadata)]
```

- 근거: `defs/`(Dagster op 래퍼), `pipeline/ops/runner.py`, `_get_file_extractor()` 어느 쪽도
  `HTMLCleanReader`의 내부 구현에 의존하지 않고 `BaseReader` 인터페이스로만 사용하므로, 클래스
  경계만 지키면 파이프라인 배선 변경이 전혀 필요 없다.
- `trafilatura.extract()`가 `None`을 반환하는 경우(본문 판별 실패) 빈 문자열로 폴백한다. 이 경우
  `validate_op`의 `min_content_chars` 체크(`ingestion.min_content_chars`, 기본 200자)에서 자연히
  걸러진다 — 별도 예외 처리 불필요.
- 추출 정책은 `settings.yaml`의 `ingestion.html_extraction_policy`(기본 `lenient`, US-39)에서 읽는다.
  하드코딩 금지 원칙(hard rule 1)에 따른 것이며, 배포별로 코드 변경 없이 값만 바꿔볼 수 있다.

---

## 4. JS 렌더링 예외 처리 (SPA 케이스, pending — 현재 도입 계획 없음)

**이 절은 설계만 해두고 구현은 보류한다.** 4.3에서 확인했듯 Playwright는 이미지 크기(+500~700MB)와
운영 복잡도(별도 Dockerfile variant, 브라우저 바이너리 관리) 부담이 큰 반면, 실제 크롤링 대상
사이트 중 SPA 비율이 얼마나 되는지, 즉 이 비용을 들일 실익이 있는지 아직 확인되지 않았다. 정적
파싱만으로 충분한 사이트가 대다수라면 이 절 전체가 불필요할 수 있다 — 운영 중 SPA로 인한 추출
실패 사례가 실제로 쌓이면 그때 재검토한다. 이하 4.1~4.4는 향후 필요해질 경우를 위한 설계
기록이며, 백로그 항목은 두지 않는다.

정적 HTML 파싱(httpx GET)으로 본문을 못 찾는 SPA(초기 HTML이 `<div id="root"></div>` 같은
빈 컨테이너만 갖는 경우)만 예외적으로 처리한다. Firecrawl 같은 별도 크롤링 스택을 도입하지
않고, 이미 필요한 지점(`WebConnector._process_page`)에만 최소 침습적으로 Playwright 단일
호출을 추가한다.

### 4.1 트리거 조건

`WebConnector._process_page`가 이미 갖고 있는 `_has_sufficient_content()`(trafilatura 추출
결과 길이가 `min_content_chars` 미만이면 False)를 그대로 재사용한다.

```
httpx GET → html
    │
    ▼
trafilatura.extract(html) 길이 >= min_content_chars ?
    │
   YES ──────────────► 기존 흐름 그대로 (S3 staging)
    │
   NO (SPA 의심)
    │
    ▼
Playwright로 동일 URL 렌더링 (headless Chromium, 단일 페이지 로드 + networkidle 대기)
    │
    ▼
렌더링된 HTML로 trafilatura.extract() 재시도
    │
   여전히 부족 ──► 기존과 동일하게 skip (S3 staging 안 함)
    │
   충분함
    │
    ▼
렌더링된 HTML을 S3에 staging (원본 정적 HTML 대신)
```

- 정적 HTML로 이미 충분한 페이지는 Playwright를 아예 실행하지 않으므로 대다수 페이지는
  기존과 동일한 비용으로 처리된다.
- S3에는 항상 "최종적으로 trafilatura가 본문을 뽑아낼 수 있었던 HTML"만 저장되므로,
  `parse_op`의 `HTMLCleanReader`는 렌더링 여부와 무관하게 동일한 정적 파싱 로직만 알면 된다
  (3.4의 인터페이스 유지 원칙과 일관).

### 4.2 설정

```yaml
# settings.yaml (안)
web_connector:
  js_render_fallback: true   # 기본값 미정 — 4.4 오픈 이슈 참고
  js_render_timeout_sec: 15
```

`WebConnector.__init__`이 다른 커넥터 옵션과 동일하게 `config.get(...)` 우선, 없으면
`get_settings()` 기본값을 따르는 기존 패턴(`min_content_chars`와 동일)을 따른다.

### 4.3 의존성 — optional extra로 분리

`playwright`는 기본 의존성이 아니라 `pyproject.toml`의 `[project.optional-dependencies]`에
신규 그룹(`playwright`)으로 추가한다. 브라우저 바이너리(`playwright install chromium`)와
그 실행에 필요한 시스템 공유 라이브러리(`playwright install-deps`, slim 베이스 이미지 기준
Chromium 하나만으로도 다운로드+설치 후 약 +500~700MB)까지 합치면 이미지 크기 부담이 크고,
JS 렌더링은 WebConnector sync 중 SPA 페이지에서만 드물게 발동하는 fallback이라 모든 배포가
이 비용을 상시 지도록 하는 것은 낭비다.

- `uv sync --extra playwright` (또는 동등한 설치 방식)로 이 그룹을 설치한 배포에서만
  `js_render_fallback`이 실제로 동작한다.
- extra가 설치되지 않은 환경에서 `js_render_fallback=true`로 설정된 경우: `import playwright`
  실패를 잡아 WARNING 로그 1회 남기고 기존 흐름(정적 파싱 결과 그대로 사용, staging skip)으로
  fallback — 크래시 없이 조용히 비활성화. `_get_file_extractor()`가 `llama-index-readers-file`
  미설치 시 이미 쓰는 것과 동일한 optional-import 패턴(`try/except ImportError` +
  `logger.warning`).
- WebConnector를 실제로 운영하는 배포(Dockerfile 빌드)에서만 `--extra playwright` +
  `playwright install --with-deps chromium`을 추가한다. 메인 API/Dagster 이미지의 기본 빌드에는
  포함하지 않는다 — 별도 Dockerfile variant 또는 build arg 분기는 구현 시점에 결정.

### 4.4 오픈 이슈

- `js_render_fallback` 기본값(true/false) — extra 미설치 환경에서는 어차피 자동 비활성화되므로
  리스크는 낮아졌지만, extra를 설치한 배포에서의 기본값은 여전히 미정. Playwright 헤드리스 브라우저
  실행 비용(수백ms~수초, 메모리)이 trafilatura 대비 훨씬 크므로, 실제 크롤링 대상 사이트의 SPA
  비율을 보고 결정 필요.
- `--extra playwright`를 포함하는 Dockerfile variant/build arg 분기의 구체적 구현 방식 미정.
- `request_delay_ms`처럼 커넥터 sync 전체 처리 시간에 Playwright fallback이 미치는 영향 — depth가
  깊은 크롤에서 SPA 페이지 비율이 높으면 sync 시간이 크게 늘어날 수 있음(재시도 시간 상한 필요 여부).
- ConfluenceConnector/GitHubConnector는 API 기반 수집이라 JS 렌더링 문제가 없음 — 이번 대응은
  WebConnector 전용.

---

## 5. 영향 범위

| 컴포넌트 | 영향 |
|---|---|
| `pipeline/ops/parse.py::HTMLCleanReader` | 내부 구현 교체 (3.4) |
| `pipeline/ops/parse.py::_get_file_extractor()` | 변경 없음 (`.html`/`.htm` → `HTMLCleanReader` 매핑 유지) |
| `connectors/web.py` | 변경 없음 (4절 pending — Playwright fallback 미구현) |
| `connectors/confluence.py` | HTML export 문서는 동일하게 `HTMLCleanReader`를 거치므로 3절 변경의
  수혜를 받음. JS 렌더링은 애초에 해당 없음(API 기반 수집) |
| `tests/unit/test_parse_html.py` | trafilatura 기반 추출로 전면 재작성 필요 — 기존 테스트는
  BeautifulSoup 태그 제거 동작(`assert "Copyright 2025" not in text` 등)을 직접 검증하므로 그대로
  통과하지 않음 |

---

## 6. 오픈 이슈 (종합)

- ~~3.2 `favor_precision=True`로 인한 본문 일부 손실 허용 범위 — 운영 데이터로 재검증 필요~~ →
  US-39에서 재검증 완료, 기본값을 `lenient`로 전환 (3.2 참고). 남은 잔여 이슈:
  - `lenient` 정책에서 짧은 boilerplate(라이선스 푸터 등)가 본문에 섞여 들어올 수 있음 — 2절
    "남는 격차"와 동일한 성격의 열린 문제.
  - `connectors/web.py`의 `_has_sufficient_content()`는 여전히 옵션 없이(중립 `balanced` 정책)
    trafilatura를 호출해 스테이징 여부를 판단한다 — 파싱 단계(`lenient`)와 게이팅 단계
    (`balanced`)가 다른 기준을 쓰는 비일관성이 있음. 이번 범위에서 다루지 않음.
  - US-39 이전에 `strict` 정책으로 이미 인제스트된 기존 HTML 문서는 자동으로 재추출되지
    않는다 — 재인제스트 필요 여부는 운영 판단.
- 3.3 마크다운 인식 청킹(`MarkdownNodeParser` 등 헤딩 단위 분할)은 범위 밖 — 별도 US 검토 대상.
  검토 결과 현재는 도입하지 않는 쪽으로 결정: `MarkdownNodeParser`는 `chunk_size` 상한 개념이
  없어 헤딩 사이 긴 섹션을 그대로 하나의 노드로 만들기 때문에 `SentenceSplitter` 보조 분할기를
  별도로 결합해야 하고, 문서마다 청크 크기 편차가 커지면 dedup stage 3(`chunk_compare`)의
  청크 수 비율 스케일링 로직(`docs/internal/design/dedup.md` "청크 수 비율 스케일링 도입" 항목)에
  다시 영향을 줄 수 있다. 현재도 markdown 구문이 텍스트에 남아있는 것만으로 `SentenceSplitter`의
  문장/줄 경계가 더 뚜렷해지는 효과는 이미 얻고 있으므로(3.3), 운영 중 HTML 문서의 검색 품질이
  실제로 떨어진다는 신호가 쌓이기 전까지는 도입하지 않는다.
- 2절 "남는 격차": 본문 블록 안에 섞인 짧은 사이트 반복 문구는 이 설계로 해결되지 않음 — 필요해지면
  connector 설정 기반 결정적 문구/셀렉터 제외 목록(통계적 자동 탐지 아님)을 별도로 검토
- 4절 전체가 pending — Playwright 도입 비용(이미지 크기, 운영 복잡도) 대비 실익(SPA 비율) 미확인.
  운영 중 SPA 추출 실패 사례가 쌓이면 재검토하고, 그때 4.1~4.4 설계를 백로그로 승격한다.

---

## 7. Dev Requirements (backlog units)

| ID | Title | Depends on |
|---|---|---|
| US-36 | HTMLCleanReader를 trafilatura 밀도 기반 추출(favor_precision, markdown 출력)로 교체 | — |
| US-39 | 추출 정책(strict/lenient/balanced) 설정화 + 기본값 lenient 전환 | US-36 |

4절(JS 렌더링, Playwright fallback)은 pending이라 백로그 항목 없음 — 재검토 시 4절 설계를
근거로 신규 US를 생성한다.
