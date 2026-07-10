# US-35: Dedup Stage 3 — 청크 단위 임베딩 비교 (chunk_compare) + 임계값 기반 body 확정

## 목적

simhash/minhash 단계에서 `similar`(근접 후보)로 라우팅된 문서 A-C 쌍에 대해, 청크 단위 임베딩 코사인
유사도를 비교하여 문서 레벨 집계 점수를 산출하고, 그 집계 점수를 임계값과 비교해 body(동일/유사/무관)를
최종 확정한다. 4단계(비율 기반 세분화 + LLM 확인, `docs/internal/design/dedup.md` 3.4)는 pending —
이번 US는 3단계까지만 구현한다.

설계 근거: `docs/internal/design/dedup.md` 3.3.2(청크 비교), 3.3.3(임계값 판정), 2.1(Verdict 구성 요소).

## 범위

- chunk_compare 단계 순수 함수 구현 (`pipeline/ops/dedup/chunk_compare.py`, simhash.py/minhash.py와 나란히)
  - A는 Qdrant에 저장하지 않고 기존 `chunk()`(pipeline/ops/chunk.py) + `embed()`(pipeline/ops/embed.py)
    순수 함수로 청크·임베딩만 즉석 계산 (in-memory) — A를 색인하는 게 아니라 검색 쿼리로만 쓰는 것
  - `infra/qdrant.py`에 `doc_id` 필터 벡터 검색 함수 신규 추가 (예: `search_chunks_by_doc_id(kb_id, doc_id,
    query_vector, top_k)`) — `delete_chunks_by_doc_id`/`update_payload_by_doc_id`가 이미 쓰는
    `qmodels.Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])` 패턴 재사용,
    `client.query_points(..., using="dense", query_filter=...)`로 구현
  - A 청크별로 이 검색 함수를 candidate C의 `doc_id`로 필터링해 호출(top_k) → threshold(0.50) 필터 → Top-1 매칭
  - 문서 레벨 집계 점수 산출: 커버리지 가중 평균 `Σ(matched score) / N` (N = A 전체 청크 수, 미매칭은 0)
  - 집계 점수 임계값 판정 → body 확정 (`identical` ≥0.95 / `similar` 0.75~0.95 / `none` <0.75)
- `run_dedup_pipeline()`(및 `dedup_ops.py`의 Dagster 래퍼) 라우팅 갱신:
  - simhash 단계 `similar` → chunk_compare로 라우팅 (현재는 verdict 직행 — 변경 필요)
  - minhash 단계 `similar` → chunk_compare로 라우팅 (현재는 verdict 직행 — 변경 필요)
  - 그 외(simhash `identical`/`title_changed`, 또는 simhash·minhash 모두 후보 없음)는 기존과 동일하게
    chunk_compare 스킵 → verdict 직행
- `dedup.compare_all_candidates` (bool, 기본값 `false`) 추가 — `false`면 `duplicate_doc_id`(best match)
  단건만, `true`면 `candidate_doc_ids` 전체를 순회. chunk_compare(3단계)·body 확정(3.3.3) 공통 적용
- settings.yaml `dedup` 섹션에 3단계 임계값 추가 (아래 "설정값" 참고)
- 로그/문서 표현은 "Stage 3" 대신 `chunk_compare` 스텝 이름 사용 (기존 simhash/minhash 스텝과 동일한 표기 원칙)

## 비범위

- 4단계 (비율 기반 세분화 + LLM 확인, "관련" verdict) — pending, 이번 US 범위 아님
- "관련" verdict 및 그 후속 처리(링크 메타데이터) — 4단계 전용이라 발생하지 않음
- 기존 문서 전체에 대한 청크 재비교 백필

## 설정값 (settings.yaml, 안)

```yaml
dedup:
  chunk_match_threshold: 0.50       # 청크쌍 필터 임계값 (Top-1 매칭 최소 점수)
  body_identical_threshold: 0.95    # 집계 점수 >= 이 값 → body identical
  body_similar_threshold: 0.75      # 집계 점수 >= 이 값(< identical) → body similar, 미만은 none
  compare_all_candidates: false     # false=best match 1건만, true=candidate_doc_ids 전체 순회
```

## Verdict 결합 (기존 2.1절 규칙 재사용, 신규 아님)

| body (chunk_compare 산출) | title | verdict | to_chunk |
|------|-------|---------|----------|
| identical | identical | `identical` | False |
| identical | similar/none | `title_changed` | False |
| similar | any | `similar` | False |
| none | — | `proceed` | True |

## 완료 기준

- simhash/minhash `similar` 판정이 chunk_compare를 거쳐 최종 body(identical/similar/none)로 확정됨을 확인
- 집계 점수가 각 임계값 구간에 따라 올바른 body로 매핑됨 (경계값 포함 테스트)
- `compare_all_candidates=true`로 설정한 경우 후보 C가 여러 개면 각각 독립적으로 판정되고, 5단계 다중 후보 우선순위 규칙(2.1절 참고)이 그대로 적용됨 (기본값 `false`는 best match 1건만 판정)
- `test_dedup_chunk_compare.py` 신규 테스트 전체 통과, 기존 `test_dedup_simhash.py`/`test_dedup_minhash.py`/`test_dedup_verdict.py` 회귀 없음

## 오픈 이슈

- **A 청크 임베딩 이중 계산:** needs_indexing=True로 결론나면 표준 `chunk_op`/`embed_op`가 A를 다시
  청크·임베딩하게 되어 동일 문서를 두 번 청크·임베딩하는 비용이 발생함. **캐싱은 포기하고 이중 계산
  비용을 감수하기로 결정** — `docs/internal/known-issues.md` 14번 항목에 등록됨, 재검토 필요 시 그쪽 참고.
- `infra/qdrant.py`에 신규 추가할 `doc_id` 필터 벡터 검색 함수의 정확한 시그니처/반환 타입 미정
  (`query_points` 반환값을 (chunk_id, score) 목록으로 감쌀지 등)
- 집계 방식(커버리지 가중 평균, `Σscore/N`)은 3.3.2에서 확정했으나, `body_identical_threshold`(0.95)
  /`body_similar_threshold`(0.75)는 원래 청크쌍 단위 밴드값을 그대로 재사용한 것 — 커버리지 가중
  평균은 미매칭 청크를 0으로 포함해 구조적으로 낮게 나오므로, 운영 데이터로 재검증 필요
  (`docs/internal/design/dedup.md` 3.3.2/3.3.3 오픈 이슈 참고)
- `compare_all_candidates` 기본값은 `false`(best match 단건)로 결정됨 — `true`(전체 후보 순회) 전환 시 Qdrant 조회 횟수 등 비용 영향은 아직 미측정
- 4단계 도입 여부/시점 — "관련" 관계 추적, LLM 확인이 필요해지면 재검토 (3.4 설계는 pending 상태로 보존됨)
