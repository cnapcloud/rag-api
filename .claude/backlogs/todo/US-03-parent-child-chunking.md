# US-03: Parent-Child 청킹 & Auto-Merge 검색

**상태**: todo

> 설계: [parent-child-chunking.md](../../docs/internal/design/parent-child-chunking.md)

## 목적

현재 청킹은 단일 레벨이라 `chunk_size`를 작게 잡으면 검색은 정밀해지지만 반환 텍스트가
문맥 없이 짧게 끊기고, 크게 잡으면 문맥은 살지만 검색 정밀도가 떨어지는 trade-off가 있다.
문서를 parent/child 계층으로 청킹하고, 검색된 child가 같은 parent 아래 일정 비율 이상
매칭되면 그 parent 텍스트로 자동 병합(auto-merge)해 정밀 검색과 문맥 복원을 동시에
달성한다. PRD [§12](../../docs/internal/requirement/prd.md#12-parent-child-청킹과-auto-merge-검색) 참고.

## 범위

- HierarchicalNodeParser 기반 N-level 청킹, 결정적 노드 ID(`id_func`) — [design §2, §3.1](../../docs/internal/design/parent-child-chunking.md#3-전체-흐름)
- `chunk()` 반환 타입 변경(`ChunkResult`) 및 `pipeline/steps/CLAUDE.md` 계약 갱신
- `parent_chunks` Postgres 테이블 신설(자기참조 트리) + 마이그레이션
- `upsert.py` 확장 — ancestor Postgres 저장 + Qdrant leaf payload에 `parent_chunk_id` 추가
- `rag/retriever.py` — auto-merge 그룹핑/재귀 병합 순수 함수, `_search_kb` 흐름에 통합
- `pipeline/utils/purge.py` — 문서 삭제(soft/hard) 시 `parent_chunks` 정리
- Settings 추가 — `chunking.strategy`에 `"parent_child"` 값 추가, `chunking.chunk_size` 타입을 `int | list[int]`로 확장, `retrieval.auto_merge.*`
- KB 오버라이드 확장 — `OVERRIDABLE_SETTINGS_PREFIXES`에 `retrieval.` 추가 + `retrieval.rerank.api_key` deny-list
- REST API 응답(`SearchResultItem`) — `merged`/`parent_chunk_id` 필드 추가
- `dedup/chunk_compare.py`, `defs/ops/ingest_ops.py`, `pipeline/runner.py` — `chunk()` 반환 타입 변경에 따른 호출부 수정
- `data-schema.md` 갱신 (Qdrant payload, `parent_chunks` 테이블)

세부 구현 방식·스키마·알고리즘은 설계 문서에 이미 있으므로 여기 반복하지 않는다 — 구현 순서와
파일별 작업은 `plans/03-parent-child-chunking.md`에 정리한다.

## 비범위

(design [§1.3](../../docs/internal/design/parent-child-chunking.md#13-비범위) 그대로)

- `semantic`/`code` 청킹 전략과의 조합
- 기존에 이미 인덱싱된 문서의 소급 재청킹
- KB 단위 재청킹 마이그레이션 도구
- 레벨별로 서로 다른 `merge_threshold` (모든 레벨 공통 값 하나만 지원)
- MCP 서버 응답에 `merged`/`parent_chunk_id` 노출 (REST API만 노출하기로 결정)

## 완료 기준

- [ ] `chunking.strategy`가 `"recursive"`/`"semantic"`(기본값)일 때 기존 단일 레벨 청킹/검색 동작이 그대로 유지된다(회귀 테스트)
- [ ] `chunking.strategy="parent_child"`인 문서를 인제스트하면 `parent_chunks`에 계층(root~leaf 바로 위)이 저장되고, Qdrant leaf payload에 `parent_chunk_id`가 채워진다
- [ ] `min_chunk_chars` 필터로 걸러진 leaf는 `child_count` 계산에서 제외되고, `child_count=0`인 ancestor는 저장되지 않는다
- [ ] 검색 시 매칭 비율이 `merge_threshold` 이상이면 parent 텍스트로 병합되고, 미만이면 개별 결과가 그대로 반환된다 (2-level 단위 테스트)
- [ ] N-level(3-level 이상) 문서에서 레벨을 타고 올라가며 반복 병합되고, 병합 실패한 결과가 상위 레벨에서 재시도되지 않는다(settled/active 분리, 단위 테스트)
- [ ] 문서 soft delete/hard delete 시 `parent_chunks`가 정리된다(dedup bands와 동일한 패턴)
- [ ] 재인덱싱(delete-then-insert) 후 `parent_chunks`가 새 내용으로 교체된다
- [ ] `dedup/chunk_compare.py`가 `chunk().nodes`만 사용하도록 수정되고 기존 dedup 테스트가 통과한다
- [ ] KB별로 `chunk_sizes`/`merge_threshold`를 오버라이드할 수 있고, `chunk_sizes` 내림차순 검증이 전역 로드/KB 오버라이드 양쪽 경로에서 모두 걸린다
- [ ] `retrieval.rerank.api_key`는 `retrieval.` 접두사가 오버라이드 허용으로 바뀐 뒤에도 여전히 오버라이드 불가 상태다(deny-list 테스트)
- [ ] REST API 검색 응답에 `merged: bool` 필드가 포함되고, `merged=true`인 결과는 `chunk_index`가 `None`이다
- [ ] 관련 테스트 전체 통과

## 의존성

없음

## 오픈 이슈

- `parent_chunk_size`/`chunk_sizes` 기본값은 초기 추정치 — 실측 후 조정 (design [§7](../../docs/internal/design/parent-child-chunking.md#7-리스크--오픈-이슈))
- 재인덱싱 시 결정적 ID(`"{doc_id}:{idx}"`)로 인한 짧은 불일치 윈도우는 수용된 리스크로 남겨둠 (design §7)
- `HierarchicalNodeParser.from_defaults()`가 레벨별로 다른 `chunk_overlap`을 지원하는지는 구현 시점에 실제 시그니처로 확인 필요 (design §7)
