# US-37: WebConnector — seed page 포함 옵션 + unrestricted 도메인 스코프 옵션 (백엔드)

**상태**: done

## 목적

WebConnector(US-18)는 "포털 페이지에서 시작해 하위 문서를 크롤링"하는 용도로 설계돼 있다.
`skip_seed_pages`(기본 `true`)가 seed 페이지 자체를 문서로 스테이징하지 않고, `_seed_prefix()`
스코프가 seed URL의 path 하위로만 크롤링을 제한한다. 평면 구조 사이트(예: 나무위키 개별
문서)를 seed로 쓰면 두 제약이 겹쳐 문서가 0건 인제스트되는 문제가 있다. 이미 있는
`skip_seed_pages`는 그대로 두고, "해당 depth 범위 안에서는 path 하위제약 없이 같은 도메인
전체를 허용"하는 신규 boolean 옵션 `unrestricted`를 백엔드에 추가해 해결한다.

Admin UI에서 이 필드들을 노출하는 작업은 [US-38](US-38-web-connector-admin-ui-unrestricted.md)로
분리한다.

## 범위

- `src/rag_api/connectors/web.py`: `WebConnector.__init__`에 `unrestricted: bool`(기본
  `False`) 파싱 + `_seed_netlocs` 계산 추가. `_should_process()` 로직을
  `unrestricted=True`일 때 seed와 동일 netloc이면 path 하위제약 없이 통과하도록 분기.
  클래스 docstring에 필드 설명 추가.
- `tests/unit/test_web_connector.py`: `TestShouldProcess`에 `unrestricted` 관련 케이스 추가
  (기본값 회귀, netloc 통과/차단, exclude/include 병행 동작).

## 비범위

- Admin UI 노출 — [US-38](US-38-web-connector-admin-ui-unrestricted.md)에서 처리.
- `depth`/`max_pages` 등 기존 크롤링 한도 필드 변경 없음 — `unrestricted`는 이 한도 안에서
  path 제약만 완화하는 옵션이다.
- `unrestricted=True`여도 seed와 다른 netloc(외부 도메인)은 계속 차단 — 도메인 전체 무제한
  크롤링은 비범위.

## 완료 기준

- [x] `unrestricted=False`(기본값)일 때 기존 scope 제약 동작이 회귀 없이 그대로임을 단위
      테스트로 확인.
- [x] `unrestricted=True`일 때 seed와 다른 path라도 같은 netloc이면 통과, 다른 netloc은
      차단됨을 단위 테스트로 확인.
- [x] `exclude_patterns`/`include_patterns`가 `unrestricted=True`에서도 기존과 동일하게
      적용됨을 단위 테스트로 확인.
- [x] `.venv/bin/python -m pytest tests/unit/test_web_connector.py -v` 전체 통과 (59 passed).
- [~] 나무위키(고양이) 커넥터를 API로 `skip_seed_pages=false`, `unrestricted=true`로
      재설정 후 sync 실행 시 seed 페이지 자신 + 직접 링크된 문서가 실제로 KB에 여러 건
      생성됨을 확인 (엔드투엔드). **waived** — Claude Code 세션에서 실행 중인 클러스터에
      접근 권한이 없어 직접 확인 불가. 사용자 판단으로 단위 테스트 통과만으로 완료 처리
      (2026-07-13). 실제 환경에서 이상 발견 시 별도 이슈로 기록.

## 의존성

없음 (US-18 WebConnector는 이미 `done`).
