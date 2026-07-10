---
name: dedup-chunk-compare-title-match-fix
description: chunk_compare(stage3) escalation이 stage1의 title_match="unknown"을 그대로 물려받아 handle_identical로 오분기되던 버그와 수정
metadata:
  type: project
---

`pipeline/ops/dedup/chunk_compare.py`의 `run_chunk_compare()`가 stage1(SimHash) `body_match="similar"`
결과를 `identical_level`로 격상시킬 때, `title_match`를 재계산하지 않고 stage1의 값(`"unknown"`, SimHash가
`identical_level`을 직접 판정했을 때만 title_match를 채우므로)을 그대로 물려받고 있었다. 그 결과
`run_verdict()`의 `if result.title_match == "changed":` 분기가 항상 실패하여, 제목이 명백히 다른 두
문서(예: `README-2.md` vs `README.md`)도 `handle_identical()`로 빠졌다. `handle_identical()`은
`_resolve_newer()`(doc_created_at 비교) 없이 **무조건 incoming(방금 재업로드한 문서)을 outdated로
마킹**하므로, 재업로드한 최신 문서가 항상 outdated가 되는 증상으로 관찰됨(2026-07-09, 사용자 보고
+ dedup_op 로그로 확인: `chunk_compare: confirmed body_match=identical_level ... score=0.976` →
`Marked outdated: doc_id=<incoming> verdict=identical`).

**Why:** `DedupResult`를 단계별로 이어받는 구조(stage1→stage3)에서, 파생 필드(title_match) 재계산을
누락하면 이후 라우팅 로직(`run_verdict`)이 조용히 잘못된 분기를 탄다. 이런 종류의 버그는 로그만 봐서는
"identical_level 맞게 나왔는데 왜 outdated?"로 보여서 날짜/설정 문제로 오해하기 쉽다.

**How to apply:** `chunk_compare.py`에 `_resolve_title_match()`를 추가해, 최종 승자 후보
(`best_doc_id`)의 저장된 `title_hash`를 `get_docs_fingerprints()`로 다시 조회해 실제 title_match를
계산하도록 수정함 ([chunk_compare.py:104-119](../../src/rag_api/pipeline/ops/dedup/chunk_compare.py#L104-L119)).
앞으로 dedup에 새 stage(예: stage4)를 추가하거나 기존 stage의 라우팅을 바꿀 때는, `DedupResult`의
파생 필드(title_match, title_hash 등)가 다음 단계로 넘어가면서도 여전히 유효한지 반드시 확인할 것 —
"이전 단계에서 계산 안 한 필드는 그대로 두면 된다"고 가정하지 말 것.

같은 README-2.md/README.md 실사례에서 집계 점수의 containment 특성 문제도 함께 발견됨 —
[[dedup-chunk-compare-containment-fix]] 참고.
