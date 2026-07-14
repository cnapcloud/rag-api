---
name: web-connector-url-encoding-dedup-pitfall
description: normalize_source_uri가 path의 percent-encoding/NFC-NFD를 통일하지 않아 같은 페이지가 인코딩 형태 차이로 문서 2건으로 중복 생성됨 (2026-07-14)
metadata:
  type: feedback
---

`pipeline/utils/source_uri.py`의 `_normalize_web_url()`은 `urlparse(url).path`를 그대로 쓴다.
`urlparse`는 path의 percent-encoding을 디코딩하지 않으므로(같은 함수의 `parse_qs(p.query)`는
자동으로 디코딩하는 것과 비대칭), 같은 페이지라도 관리자가 브라우저 주소창에서 복사한
raw-Hangul seed URL(`/w/고양이`)과 `WebConnector._discover_links()`가 크롤링 중 수집한
percent-encoded `<a href>`(`/w/%EA%B3%A0%EC%96%91%EC%9D%B4`, MediaWiki류 사이트에서 흔함)가
서로 다른 문자열로 정규화되어 `UNIQUE(kb_id, source)` 제약을 각각 통과 → 문서 2건 생성.
한글 유니코드 조합형(NFC)/분해형(NFD) 차이도 같은 클래스의 문제(브라우저 주소창에는 동일하게
보이지만 바이트 단위로 다름).

**Why:** 나무위키 커넥터(연결 ID `b94692af7e75444c`) 동기화에서 `https://namu.wiki/w/고양이`
하나가 doc_id `130eaf696858488e`/`e1eec932de424dd7` 두 건으로 중복 생성된 것을 확인.

**How to apply:** `normalize_source_uri("web", ...)`/`("confluence", ...)`를 쓰는 곳(커넥터
`sync()`의 seed_url 정규화, BFS 크롤링 중 링크 정규화, API에서 source로 doc 조회하는 경로)은
모두 이 정규화를 거치므로 별도 조치 불필요 — 이미 `unquote()` + `unicodedata.normalize("NFC",
...)`로 수렴하도록 고쳤다([source_uri.py](../../src/rag_api/pipeline/utils/source_uri.py)).
새로운 source_type 정규화 함수를 추가할 때(예: github 외 다른 코드호스팅) path에 non-ASCII가
들어갈 수 있다면 동일하게 unquote+NFC를 적용할 것. 회귀 테스트:
`tests/unit/test_source_uri.py`.

**미해결로 남긴 부분:** 이미 중복 생성된 기존 문서 2건(위 doc_id)은 이 수정이 소급 적용되지
않는다 — 필요 시 별도로 source 값을 재정규화해 병합하는 backfill이 필요.
