---
name: dedup-settings-nested-by-stage
description: DedupSettings를 stage별(simhash/minhash/chunk_compare) 하위 모델로 재구성함 — 기존 flat 필드 경로는 더 이상 유효하지 않음
metadata:
  type: project
---

`DedupSettings`(`config/settings.py`)가 14개 flat 필드에서 stage별 하위 모델로 재구성됨
(2026-07-09, 사용자 요청 — "속성이 각 스텝과 관련없이 만들어져 직관성이 떨어진다"):

- `DedupSettings.enabled`만 최상위에 남고, 나머지는 `simhash`(Stage1) / `minhash`(Stage2) /
  `chunk_compare`(Stage3) 세 하위 모델로 분리됨.
- `settings.yaml`/`docker/settings.yaml`의 `dedup:` 섹션도 동일하게 중첩 구조로 변경.
- 예: `cfg.dedup.hamming_identical_threshold` → `cfg.dedup.simhash.hamming_identical_threshold`,
  `cfg.dedup.user_words_path` → `cfg.dedup.minhash.user_words_path`,
  `cfg.dedup.compare_all_candidates` → `cfg.dedup.chunk_compare.compare_all_candidates`.

**Why:** 기존엔 SimHash/MinHash/chunk_compare 세 단계 파라미터가 한 flat namespace에 섞여 있어서
이름만 보고 어느 단계 것인지 알기 어려웠음. 사용자가 명시적으로 "실제로 분리하는(실질적 리팩터)"
옵션을 선택함 — 단순 주석 재배열이 아니라 Pydantic 모델 자체를 stage별로 분리.

**How to apply:** `pipeline/ops/dedup/simhash.py`/`minhash.py`/`chunk_compare.py`의 함수들은 이제
`DedupSettings` 전체가 아니라 각자의 하위 설정 타입(`SimHashSettings`/`MinHashSettings`/
`ChunkCompareSettings`)을 `cfg` 파라미터로 받는다. 호출부(`pipeline/ops/dedup/__init__.py`의
`run_dedup_pipeline()`)가 `cfg.dedup.simhash`/`cfg.dedup.minhash`/`cfg.dedup.chunk_compare`로
쪼개서 넘긴다. 앞으로 dedup 설정을 참조하는 새 코드를 작성하거나 문서를 검색할 때, 옛 flat 경로
(`dedup.<field>`)가 코드/문서/backlog 어딘가에 남아 있으면 stage 하위 경로로 바꿔야 한다 — 단
`.claude/backlogs/`, `.claude/plans/`의 완료된 항목(예: US-25, US-35)은 당시 시점 기록이라
그대로 두었음(과거 기록 수정 안 함).
