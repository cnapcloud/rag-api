---
name: dedup-chunk-compare-containment-fix
description: chunk_compare(stage3) 집계 점수가 containment(포함도)라서 크기 차이 큰 문서쌍도 identical/similar로 오판되던 문제와 청크 수 비율 스케일링 수정
metadata:
  type: project
---

`pipeline/ops/dedup/chunk_compare.py`의 문서 레벨 집계 점수(`Σ(matched score_i) / N`, N=A 전체
청크 수)는 IR 문헌의 **containment(포함도, Broder 1997 "On the Resemblance and Containment of
Documents")** 공식과 동일하다. A가 훨씬 큰 문서 C의 일부(예: 서론 한 섹션)와만 겹쳐도 A의 청크
전부가 매칭되면 점수가 1.0에 가깝게 나와 `identical_level`로 오판된다. 이건 "A와 C가 같은 문서"가
아니라 "A가 C에 포함된다"는 뜻일 뿐이라, resemblance(대칭 유사도)와는 다른 질문에 답하는 지표다
(2026-07-09, 사용자가 README-2.md/README.md 사례로 지적).

**Why:** containment는 원래부터 비대칭 지표라 "같은 문서인지"를 판정하는 데 그대로 쓰면 안 된다는
게 IR 분야에서 이미 정리된 문제([[dedup-chunk-compare-title-match-fix]]와 마찬가지로 이번에도
같은 README-2.md/README.md 페어에서 발견됨 — 두 문제는 원인이 다르지만 같은 실사례에서 함께
드러났다). 대칭 지표(C도 임베딩해서 A와 역방향 매칭)로 바꾸면 계산 비용이 커지므로(이미
known-issues #14에서 A 재계산 비용을 "받아들인 비용"으로 명시), 새 threshold 없이 기존
`body_similar_threshold`/`body_identical_threshold`를 재사용하는 저비용 보정을 택함.

**How to apply:** `compare_chunks()`가 candidate의 Postgres `chunk_count`를 조회해
`chunk_ratio = min(A청크수, C청크수) / max(A청크수, C청크수)`를 계산하고, raw_score에 곱한 뒤
기존 threshold로 판정한다 ([chunk_compare.py:47-107](../../src/rag_api/pipeline/ops/dedup/chunk_compare.py#L47-L107)).
`chunk_ratio`가 `body_similar_threshold` 미만이면 raw_score가 1.0이어도 스케일링 후 threshold를
못 넘는 게 수학적으로 보장되므로 embed+Qdrant 검색 자체를 생략한다(비용 최적화, 새 판단 기준
아님). 설계 문서 갱신: [dedup.md 3.3.2](../../docs/internal/design/dedup.md) "청크 수 비율
스케일링 도입" 항목 참고. 앞으로 dedup 집계 점수 관련 로직을 건드릴 때는 "이 점수가 containment인지
resemblance인지"를 먼저 구분할 것 — 두 값을 섞어 쓰면 크기 비대칭 문서쌍에서 조용히 오판이 생긴다.
