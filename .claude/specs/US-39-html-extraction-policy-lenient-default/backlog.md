# US-39: HTML 추출 정책(strict/lenient/balanced) 설정화 + 기본값 lenient 전환

**상태**: done

> 설계: [html-extraction.md](../../../docs/internal/design/html-extraction.md) (§3.2, §6)

## 목적

`HTMLCleanReader`(US-36)가 기본으로 쓰는 `favor_precision=True`가 위키형 페이지(namu.wiki)에서
본문의 90%+ 를 "애매한 블록"으로 오판해 통째로 버리는 사례가 확인됐다(kb-02,
doc_id=`b950892c61d1463c`, "최고령 고양이" 섹션 전체 누락 — 실제 청크 9개/7.8KB vs
`favor_recall=True`로 재추출 시 105KB). trafilatura 소스(`settings.py:143`)를 보면
`favor_precision`/`favor_recall`은 실제로는 `strict`/`lenient`/`balanced` 3단계 중 하나를
고르는 것과 같고(`lenient`이 우선), 이 tri-state를 그대로 설정으로 노출해 운영자가 선택할 수
있게 하고 기본값을 `lenient`로 전환한다.

## 정책 정의 (요건)

세 정책은 "본문인지 애매한 블록을 얼마나 적극적으로 포함시키는가"라는 하나의 축 위에 있다
(`trafilatura==2.1.0` 소스 확인, 상세 표는 [html-extraction.md §3.2](../../../docs/internal/design/html-extraction.md#32-추출-정책--strict--lenient--balanced-us-39-2026-07-13-갱신) 참고):

| 정책 | 판단 기준 | 대표 트레이드오프 |
|---|---|---|
| `strict` | 애매하면 제외 (PRECISION_DISCARD_XPATH 등 추가 삭제 규칙 적용) | 본문 일부가 boilerplate로 오판되어 손실될 수 있음 — namu.wiki 사례에서 90%+ 손실 실측 |
| `balanced` | 표준 임계치, 정책 전용 강화/완화 로직 미적용 | strict/lenient 중간 — 이번 이슈의 직접 원인은 아니었으나 검증되지 않은 중립값 |
| `lenient` (기본값) | 애매하면 포함 (`<p>` 전량 소실 시 정리 롤백, teaser 삭제 생략 등) | 라이선스 푸터 등 짧은 boilerplate가 본문에 섞여 들어올 수 있음 — 실측 확인됨 |

## 범위

- `IngestionSettings.html_extraction_policy: Literal["strict","lenient","balanced"] = "lenient"`
  추가 — 기존 `html_favor_precision: bool` 필드 대체
- `HTMLCleanReader.load_data()`(`pipeline/ops/parse.py`)가 policy 값에 따라
  `favor_precision`/`favor_recall` kwargs를 매핑해 trafilatura에 전달하도록 수정
- `settings.yaml`, `docker/settings.yaml`,
  `k8s/manifests/llm/rag-api/kustomize/overlays/dev/configmaps/settings.yaml`,
  `k8s/manifests/llm/dagster/kustomize/overlays/dev/configmaps/settings.yaml` 반영
- `tests/unit/test_parse_html.py` 갱신: 기존 `html_favor_precision` 단일 필드 테스트를
  3-정책 매핑 테스트로 교체, "no extractable content" fixture를 (lenient 정책에서도 항상
  빈 결과가 나오는) 진짜 무텍스트 케이스로 교체
- `docs/internal/design/html-extraction.md` §3.2(정책 선택 근거)/§6(오픈 이슈) 갱신
- `docs/internal/known-issues.md`에 이번 케이스 기록

## 비범위

- 이미 인제스트된 기존 문서(구 `favor_precision=True`로 얇게 청크된 문서)의 일괄
  재인제스트/백필은 범위 밖 — 필요해지면 별도 US로 진행
- `connectors/web.py`의 `_has_sufficient_content()`는 현재 trafilatura를 옵션 없이(중립
  모드) 호출해 스테이징 여부를 판단하는데, 이 게이팅 기준은 이번 범위에서 바꾸지 않는다 —
  파싱 단계(`lenient`)와 게이팅 단계(중립)가 서로 다른 기준을 쓰는 비일관성은 오픈 이슈로 남김

## 완료 기준

- [x] `html_extraction_policy`의 3개 값(`strict`/`lenient`/`balanced`)이 각각 올바른
      `favor_precision`/`favor_recall` kwargs 조합으로 trafilatura에 전달됨 (테스트)
- [x] 기본값 `lenient`로 변경한 후에도 기존 HTML 파싱 동작(boilerplate 제외, markdown 구조
      보존, no-content 케이스에서 빈 텍스트 반환)이 유지됨
- [x] `settings.yaml` 계열 4개 파일 모두 `html_extraction_policy` 반영
- [x] `tests/unit/test_parse_html.py` 전체 통과 (unit 스위트 400 passed, 1 skipped)
- [x] 세 정책의 실제 동작 차이(판단 기준/트레이드오프)가 "정책 정의" 절과 설계 문서 §3.2에
      명시됨 — 애초 "kwargs가 올바르게 전달되는지"만 검증하고 놓쳤던 요건, 사후 보완

## 의존성

- US-36 — `HTMLCleanReader`의 trafilatura 밀도 기반 추출 도입이 선행되어 있어야 함(완료)

## 오픈 이슈

- WebConnector 게이팅(`_has_sufficient_content`)과 `parse.py` 추출 정책 불일치 — 비범위 참고
- 기존에 이미 인제스트된 HTML 문서들의 백필(재인제스트) 필요 여부는 운영 판단 대상
