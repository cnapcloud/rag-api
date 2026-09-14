# US-55: 검색 캐시 lookup/store 데코레이터 통합 + 캐시 게이트 훅(set_cache_gate) 추가 — 설계

> 담당: `designer` · spec 워크플로우 2단계 · 템플릿: `.claude/templates/design.md`

**대상**: [spec.md](spec.md)

## 아키텍처 개요

- 컴포넌트 흐름: `api/routers/search.py` → `query/search_cache.py`(캐시 사용 여부 판단 +
  게이트 훅 레지스트리) → `infra/search_cache.py`(Redis I/O, 변경 없음)
- 신규/변경 모듈:
  - `src/rag_api/query/search_cache.py` (수정) — `set_cache_gate`/게이트 상태 + 판단 로직
    통합(데코레이터) 추가
  - `src/rag_api/api/routers/search.py` (수정) — lookup/store 호출부를
    `cache_cfg.enabled` 조건문으로 감싸던 방식을 무조건 호출로 단순화(게이트 판단은
    `search_cache` 내부로 이동)
- 관련 설계 문서: (없음 — US-53/US-54가 만든 `search_cache` 모듈 위의 순수 리팩터링이며
  `docs/internal/design/`에 대응하는 신규 토픽 문서를 만들 만큼 구조가 바뀌지 않는다)

이 리팩터링은 새 레이어를 만들지 않는다 — 게이트 상태(등록된 훅)와 판단 함수는 기존
`query/search_cache.py`(도메인 로직 레이어) 안에 모듈 레벨로 둔다. `infra/search_cache.py`는
전혀 건드리지 않는다(Redis I/O는 이 변경과 무관).

## 영향 레이어 / 파일

| 레이어 | 파일 | 변경 내용 |
|---|---|---|
| Query (도메인) | `src/rag_api/query/search_cache.py` | 수정 — 모듈 레벨 `_cache_gate` 상태 + `set_cache_gate(fn)` 추가, `lookup`/`store`를 감싸는 공통 판단 헬퍼(`_cache_usable(kb_ids, cfg)`) 추가, 두 함수 모두 이 헬퍼로 게이트 |
| API | `src/rag_api/api/routers/search.py` | 수정 — `if cache_cfg.enabled:` 로 lookup/store를 감싸던 조건 분기 제거, `search_cache.lookup`/`search_cache.store`를 무조건 호출(내부에서 게이트 판단). `cache_status` 계산(`"miss" if cache_cfg.enabled else "disabled"`)은 F3 보존을 위해 그대로 유지 |
| Query (테스트) | `tests/query/test_search_cache.py` (경로 미확인 시 기존 US-53/54 테스트 파일 위치 그대로) | 수정 — 게이트 미등록 시 기존 동작 회귀 테스트 유지, 신규 F1/F2 테스트 추가 |
| API (테스트) | 기존 `/api/search` 관련 테스트 | 필요 시 최소 수정(F3-5) |

역방향 참조 없음: `query/search_cache.py`는 계속 `infra/search_cache.py`만 참조하고,
API 레이어(`search.py`)만 `query/search_cache.py`를 참조한다(기존 의존 방향 그대로,
CLI→API→Pipeline/Query→Infra 순방향 유지).

## 신규 의존성

(없음) — 표준 라이브러리(`typing.Callable`)만 사용.

## API 계약

(해당 없음 — `/api/search`, `/api/search/cache` 요청/응답 스키마 변경 없음. 이 spec은
내부 판단 로직 통합 + Python 레벨 훅 등록 함수(`set_cache_gate`) 추가만 다룬다.)

## 데이터 모델

(해당 없음 — Redis 캐시 엔트리 스키마, `CacheSettings` 필드 변경 없음)

## 에러 모델

- `set_cache_gate(fn)` 자체는 등록 동작만 하므로 예외를 던지지 않는다(단순 대입).
- **오픈 이슈 해소**: 등록된 훅 함수(`fn(kb_ids)`)가 예외를 던지는 경우 — 판단 헬퍼
  `_cache_usable`을 `lookup`/`store`의 기존 `try/except Exception` 블록 **안에서** 호출한다.
  즉 훅 예외는 새로운 예외 클래스나 별도 처리 경로를 만들지 않고, 기존 fail-open/무시
  정책을 그대로 물려받는다:
  - `lookup` 내부에서 훅이 예외를 던지면 → 기존 `except Exception` 이 잡아 `logger.warning`
    후 `(None, None)`(캐시 미스처럼 폴백) 반환.
  - `store` 내부에서 훅이 예외를 던지면 → 기존 `except Exception`이 잡아 `logger.warning`
    후 저장을 건너뜀(무시).
  - rag-api 자체는 훅을 등록하지 않으므로 이 경로는 F3(기존 동작 보존)에 영향을 주지
    않는다 — 훅이 None일 때 `_cache_usable`은 `cfg.enabled`만 보고 결정하며 예외 발생
    여지가 없다.

## 로깅

- `_cache_usable`이 게이트에 의해 캐시를 막은 경우(훅이 `False` 반환) 별도의 신규 로그를
  추가하지 않는다 — `lookup`은 조용히 `(None, None)`을 반환하고 실제 검색으로 폴백하며,
  `store`는 조용히 저장을 생략한다. rag-api 자체 실행 시(훅 미등록) 이 경로는 절대
  타지 않으므로 F3-4(로그 메시지 100% 동일)에 영향 없음. (게이트로 막힌 요청에 대한
  가시성이 필요해지면 별도 후속 작업에서 `logger.debug` 추가 검토 — 이번 spec 범위
  아님, 오픈 이슈로 아래 기록)

## NFR

(해당 없음 — spec.md에 명시된 NFR 없음)

## 리스크 & 롤백

- 리스크: 판단 로직을 한 곳(`_cache_usable`)으로 모으는 리팩터링이 기존 `if cache_cfg.enabled:`
  분기의 미묘한 순서/조건을 놓칠 수 있다(F3 회귀). 완화책: `lookup`/`store` 각각의 기존
  동작(로그 문구, 반환 타입, exact/semantic 분기)은 손대지 않고 함수 진입부에
  `if not _cache_usable(kb_ids, cfg): return <기존 미사용 시 반환값>`만 추가하는 최소
  변경으로 제한한다. 기존 `try/except` 블록 구조도 유지한다.
- 리스크: 라우터에서 `if cache_cfg.enabled:` 분기를 제거하면 `cache_cfg.enabled=False`여도
  `search_cache.lookup`/`store` 함수 호출 자체는 발생한다(단, 내부에서 즉시 반환). 이
  호출 오버헤드는 무시 가능한 수준(조건 분기 하나)이라 성능 리스크 없음.
- 롤백: 커밋 revert로 충분하다 — 스키마/데이터 마이그레이션 없음, 순수 코드 리팩터링.

## 오픈 이슈

- 게이트로 캐시가 막힌 요청에 대한 별도 로그/`cache_status` 값(예: `"gated"`)을 둘지는
  이번 spec 범위 밖으로 남긴다 — spec.md F1~F3 완료 기준 어디에도 요구되지 않으며, 추가
  시 `SearchMeta.cache_status`의 API 계약 확장이 필요해 별도 US로 분리하는 것이 낫다.
  rag-ent-api가 필요로 하면 후속 spec에서 다룬다.

## 설계 검토 체크

- [x] `architecture` 스킬 기준 레이어/의존성 방향 확인 완료 (역방향 참조 없음)
- [x] spec.md의 모든 완료 기준(AC)이 이 설계로 커버됨
- [x] 오픈 이슈 없음 (또는 있다면 이유와 함께 명시) — 훅 예외 처리 방침은 위 "에러 모델"에서
      확정했고, `cache_status` 확장 여부만 후속 과제로 남김
