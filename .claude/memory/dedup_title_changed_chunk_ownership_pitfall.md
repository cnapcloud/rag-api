---
name: dedup-title-changed-chunk-ownership-pitfall
description: title_changed(A 최신) 처리에서 Qdrant payload doc_id를 A로 재태깅하지 않으면 indexed 문서가 청크 0개로 남음 (2026-07-14)
metadata:
  type: feedback
---

`pipeline/step/dedup/verdict.py`의 `handle_title_changed()` — incoming(A)이 기존(C)보다 최신일
때, 본문이 동일해 재임베딩하지 않고 C가 물리적으로 보유한 Qdrant 청크를 그대로 재사용한다. 이때
`update_payload_by_doc_id()`로 `title`/`source`만 A 값으로 덮어쓰고 payload의 `doc_id` 필드를
그대로 두면, 청크는 계속 C(이제 `status=outdated`)에 귀속된 채로 남고 A는 `status=indexed`인데
`chunk_count`가 NULL("—")인 빈 문서로 표시된다. 검색은 Qdrant를 직접 질의하므로 실제 검색
결과는 outdated로 표시되는 C의 doc_id를 인용하게 되는 모순이 생긴다.

**Why:** 실사용 중 동일 본문·제목만 다른 문서 재업로드 후 문서 목록에서 관측됨 — indexed 문서
청크 0개, outdated 문서가 실제 청크(134개)를 보유. `docs/internal/design/dedup.md` 3.5절
설계 자체가 애초에 청크 소유권 이전(payload `doc_id` 재태깅, Postgres `chunk_count` 이관)을
명시하지 않고 있었음 (설계-구현 불일치라기보다 설계 공백).

**How to apply:** dedup verdict 처리에서 "본문 동일 → 기존 청크 재사용" 패턴을 새로 만들 때는
반드시 (1) Qdrant payload의 `doc_id`까지 새 소유 문서로 갱신하고 (2) Postgres 쪽 `chunk_count`를
이관해야 한다 — `title`/`source`만 갱신하고 넘어가면 이번과 같은 "indexed인데 청크 없음" 증상이
재발한다. 설계 반영: `docs/internal/design/dedup.md` 3.5절 "제목변경 처리". 회귀 테스트:
`tests/unit/test_dedup_verdict.py::test_title_changed_a_newer_transfers_chunk_count`.

**미해결로 남긴 부분:** `similar` 판정에서도 청크를 완전 삭제한 outdated 문서의 `chunk_count`가
갱신되지 않아 이력값치고 오해 소지가 있음(청크 0개인데 과거 숫자가 그대로 표시) — 이번 스코프
밖이라 `dedup.md` 오픈 이슈로만 기록, 별도 처리 필요.
