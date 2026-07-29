# Parent-Child 청킹 & Auto-Merge 검색 설계

> 요건: [prd.md §12](../requirement/prd.md#12-parent-child-청킹과-auto-merge-검색)

순수 아키텍처 설계 문서. 상세 구현(SQL 마이그레이션 파일, 실제 코드)은 이 문서 승인 후
backlog/plan 단계에서 진행한다. 현재 청킹/검색 구조는
[llamaindex-integration.md](llamaindex-integration.md), [data-schema.md](data-schema.md) 참고.

---

## 1. 배경 및 목표

### 1.1 문제

현재 청킹(`pipeline/steps/chunk.py`)은 단일 레벨이다 — `chunk_size`를 작게 잡으면 검색 정밀도는
좋아지지만 반환되는 텍스트가 문맥 없이 짧게 끊기고, 크게 잡으면 문맥은 살지만 벡터 하나에 여러
주제가 섞여 검색 정밀도가 떨어진다.

### 1.2 목표

- **leaf**(가장 작은 청크, 실제 임베딩·검색 대상)로 정밀 검색을 유지하면서, 검색된 leaf가 같은
  상위 청크(ancestor) 아래 여러 개 매칭되면 그 ancestor의 전체 텍스트로 자동 교체해 응답한다
  (auto-merge). 매칭이 계속 이어지면 그 위 레벨로 반복 병합될 수 있다 — **N-level 지원**(§4.1,
  §5.1).
- ancestor 텍스트는 임베딩 대상이 아니므로 Qdrant가 아닌 Postgres에 저장한다 (하드 룰 6).
- 전체 기능은 opt-in — 비활성 시 기존 단일 레벨 청킹/검색 동작과 100% 동일하다.

### 1.3 비범위

- `semantic`/`code` 청킹 전략과의 조합 미지원 — `chunking.strategy`는 `"recursive"`/`"semantic"`/
  `"hierarchical"` 중 하나만 가질 수 있는 단일 값이라(§6), 애초에 동시에 켜지는 조합이
  존재하지 않는다. code 파일은 `strategy`와 무관하게 별도 경로로 처리된다(기존과 동일).
- 기존에 이미 인덱싱된 문서의 소급 재청킹 미포함 — 옵션 활성화 이후 신규/재인덱싱 문서부터
  적용. 기존 문서는 `parent_chunk_id = NULL`로 검색되어 자동으로 auto-merge에서 제외된다(§5.2).
- KB 단위 재청킹 마이그레이션 도구 — 필요 시 별도 backlog.
- 레벨별 서로 다른 `merge_threshold` — 모든 레벨에 동일한 임계값을 적용한다(LlamaIndex
  `AutoMergingRetriever`와 동일한 관례).

---

## 2. 아키텍처 결정 (확정)

| 결정 사항 | 선택 | 핵심 이유 |
|-----------|------|-----------|
| 청킹 구현 | LlamaIndex `HierarchicalNodeParser` (`chunk_sizes`는 큰 것→작은 것 순 리스트, **N-level**) | 레벨이 몇 개든(`chunk_sizes` 길이) parent/child 분할과 레벨 간 관계 추적을 라이브러리에 위임한다. |
| 노드 ID | `id_func` 오버라이드로 각 노드 ID를 생성 시점부터 `"{doc_id}:{idx}"`로 결정적 생성 (`idx`는 문서 전체에 걸친 전역 카운터, `simhash_bands.band_id`와 동일한 패턴) | relationship이 구축된 *뒤에* ID를 바꾸면 포인터가 깨진다 — 생성 시점부터 결정적 ID를 쓰는 것이 유일하게 안전한 순서(§3.1). `level`을 ID 문자열에 넣지 않는 이유는 순수 유일성 목적이었을 뿐 성능과 무관했기 때문 — `chunk_index`를 레벨별 리셋이 아니라 전역 카운터로 바꾸면 `level` 없이도 유일하다. `level`은 별도 컬럼으로만 유지(§4.1) — merge 알고리즘(§5.1)은 `level`을 읽지 않고 `parent_id` 체인만 사용한다. |
| Auto-merge 로직 | `rag/retriever.py` 커스텀 재귀 함수 (`AutoMergingRetriever` 미사용) | Qdrant는 커스텀 flat payload를 쓰고 LlamaIndex 표준 노드 직렬화(`_node_content`)를 쓰지 않으므로, 검색 시점엔 `node.relationships`가 이미 사라진 상태다 — ancestor 정보는 인제스트 시점에 relationship을 한 번 읽어 `parent_chunk_id` 문자열로 옮겨둔 것만 남는다(§5). `AutoMergingRetriever`를 쓰려면 wrapper retriever + 완전한 노드 그래프 docstore가 추가로 필요해 커스텀 함수보다 비용이 크다 — N-level 재귀도 기존 단일 홉 로직을 반복문으로 감싸는 수준이라 여전히 더 가볍다(§7). |
| Ancestor 저장 시점 | `upsert.py` 확장 | 이미 side-effect가 허용된 지점 — Qdrant leaf 업서트와 Postgres ancestor 저장을 한 함수 안에서 순서대로 처리. |

신규로 필요한 컴포넌트는 Postgres 테이블 하나(`parent_chunks`, 자기참조 트리 — §4.1)와
`retriever.py`의 순수 함수 하나(§5.1)뿐이다.

---

## 3. 전체 흐름

### 3.1 인제스트

```
parse()                              변경 없음 — Document.metadata["doc_id"] 포함
   │
   ▼
chunk()                              chunking.strategy="hierarchical"이면:
   │                                   1) HierarchicalNodeParser.from_defaults(
   │                                        chunk_sizes=cfg.chunk_size, ...)   # 이 시점 cfg.chunk_size는
   │                                        리스트([가장 큰 것, ..., leaf 크기]) — HierarchicalNodeParser
   │                                        쪽 파라미터명이 chunk_sizes(복수)라 그대로 전달만 함
   │                                      documents를 분할. id_func을 주입해 모든 비-leaf 노드
   │                                      ID를 처음부터 "{doc_id}:{idx}"(idx는 문서 전체 전역
   │                                      카운터)로 결정적 생성 (순서 중요 — §2)
   │                                   2) get_leaf_nodes(all_nodes) → 실제 임베딩·검색 대상(leaf)
   │                                      비-leaf 레벨(level=0..N-2) 전체 노드 → ancestor 목록
   │                                   3) 각 leaf의 relationships[NodeRelationship.PARENT].node_id
   │                                      (바로 위 레벨의 결정적 ID)를 한 번 읽어
   │                                      leaf.metadata["parent_chunk_id"]에 기록 — 이후 파이프라인은
   │                                      relationship 객체가 아니라 이 문자열만 사용(§5)
   │                                   4) 각 ancestor의 child_count는 min_chunk_chars 필터를 통과한
   │                                      실제 leaf 수로 계산 — HierarchicalNodeParser의
   │                                      relationships[CHILD] 원본 길이를 그대로 쓰지 않는다(필터로
   │                                      걸러진 leaf까지 세면 비율이 항상 낮게 나옴). 필터 후
   │                                      child_count=0인 ancestor는 저장하지 않는다(§4.1, §5.1
   │                                      ZeroDivisionError 방지)
   │                                   5) strategy가 "recursive"/"semantic"이면 기존과 동일한
   │                                      단일 레벨 분할 (타입 구조상 hierarchical와 동시에
   │                                      켜질 수 없음 — §6)
   │                                   atomic(table/image_caption)·code 파일은 기존과 동일하게
   │                                   별도 경로로 처리되고, HierarchicalNodeParser는 "text" 경로
   │                                   에만 적용된다(§1.3) — 분기 구조 자체는 변경 없음
   ▼
embed()                               leaf만 임베딩 (ancestor는 임베딩 대상 아님, 변경 없음)
   │
   ▼
upsert()                              1) delete_parent_chunks_by_doc(doc_id) — Postgres
                                       2) save_parent_chunks(doc_id, ancestors) — Postgres,
                                          root(level 0)부터 순서대로 insert(자기참조 FK 때문에
                                          parent가 먼저 존재해야 함)
                                       3) delete_chunks_by_doc_id + upsert_chunks — Qdrant (기존과
                                          동일, payload에 parent_chunk_id 필드만 추가, leaf 바로
                                          위 레벨 하나만 가리키면 충분 — 트리 전체 경로는 Postgres
                                          쪽에서 parent_id를 따라 올라가며 조회)
```

parent 저장이 Qdrant 업서트보다 먼저 실행되어야 한다 — leaf가 참조하는 `parent_chunk_id`가
Postgres에 존재하는 상태여야 검색 시점의 ancestor 존재 확인(§5.2)이 정상 동작한다.

### 3.2 검색

```
retriever._search_kb(kb_id, query, ...)
   │
   ▼
index.as_retriever().retrieve(query)        기존과 동일 — leaf 결과 반환 (parent_chunk_id 포함)
   │
   ▼
[auto_merge.enabled] _auto_merge_parents()  신규 순수 함수 (rag/retriever.py) — §5, 레벨을 타고
   │                                         올라가며 반복 적용. KB 단위로 수행 — 여러 KB를
   │                                         합치기(RRF) 전에 끝나야 함
   ▼
_filter_orphaned_chunks()                   기존과 동일
   │
   ▼
rrf_merge() / similarity sort               기존과 동일
   │
   ▼
rerank (optional)                           기존과 동일
```

`_auto_merge_parents()`는 `mode="hybrid"`/`"similarity"` 어느 쪽이든 `_search_kb()`가 만든
`list[SearchResult]`를 그대로 받아 `parent_chunk_id` 문자열만으로 동작하므로, 어떤 모드로
만들어진 결과인지 신경 쓰지 않는다 — 두 모드 모두 동일하게 적용된다.

### 3.3 삭제

```
delete_doc(doc_id)
   │
   ▼
_delete_qdrant_chunks()                     기존과 동일
   │
   ▼
_delete_db_record()
   ├─ purge_doc_artifacts()                 delete_simhash_bands, delete_minhash_bands와 동일한
   │                                          자리에 delete_parent_chunks_by_doc(doc_id) 추가 —
   │                                          soft delete에서도 정리
   ▼
soft_delete_doc() / hard_delete_doc()       hard delete는 documents 삭제 시 parent_chunks 전체
                                             레벨이 ON DELETE CASCADE로 자동 정리됨(§4.1). purge
                                             호출은 멱등하므로 중복 실행돼도 안전.
```

재업로드(reindex)는 인제스트 흐름(§3.1)의 delete-then-insert로 자연스럽게 처리된다.

---

## 4. 저장 스키마

### 4.1 Postgres — `parent_chunks` 테이블 (신규, 자기참조 트리)

```
parent_chunks
├── chunk_id      TEXT         PRIMARY KEY   -- "{doc_id}:{idx}" (idx = 문서 전체 전역 카운터,
│                                                simhash_bands.band_id와 동일한 합성 키 패턴 —
│                                                level별로 리셋하지 않으므로 level 없이도 유일)
├── doc_id        TEXT         NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE
├── kb_id         TEXT         NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE
├── level         SMALLINT     NOT NULL   -- 0 = root(가장 큰 덩어리) ... leaf 바로 위 레벨까지.
│                                            조회/디버깅용 — merge 알고리즘(§5.1)은 이 컬럼을
│                                            읽지 않고 parent_id 체인만 따라간다
├── parent_id     TEXT         REFERENCES parent_chunks(chunk_id) ON DELETE CASCADE  -- NULL=root
├── chunk_index   INTEGER      NOT NULL   -- 같은 level 내 시퀀스 번호 (0-based, 표시/디버깅용)
├── text          TEXT         NOT NULL   -- 이 노드 전체 텍스트 (auto-merge 응답에 그대로 사용)
├── child_count   INTEGER      NOT NULL   -- 바로 아래 레벨의 실제 자식 수. min_chunk_chars
│                                            필터를 통과해 실제로 존재하는 자식 수만 센다 —
│                                            HierarchicalNodeParser의 relationships[CHILD] 원본
│                                            길이를 그대로 쓰면 필터링된 leaf까지 포함돼 비율이
│                                            항상 실제보다 낮게 나온다(§3.1). child_count가 0이
│                                            되는 ancestor(자식이 전부 필터링된 경우)는 이 테이블에
│                                            아예 저장하지 않는다 — §5.1의 `len(children) /
│                                            child_count`에서 ZeroDivisionError를 방지
├── page_num      INTEGER      -- 이 ancestor가 속한 Document(페이지)의 page_num. 청킹이
│                                 Document 단위(PDF는 페이지당 1개)로 이뤄지고 서로 다른
│                                 Document의 텍스트가 한 노드로 합쳐지는 일이 없으므로, ancestor도
│                                 leaf와 동일하게 자기 소속 Document의 값을 그대로 상속받는
│                                 단일 값이다(범위 계산 불필요). 비페이지네이션 문서는 NULL
├── page_label    TEXT         -- 위와 동일한 이유로 leaf와 동일하게 단일 값 상속. NULL 규칙도 동일
├── created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
```

Index: `idx_parent_chunks_doc` on `(doc_id)`, `idx_parent_chunks_parent` on `(parent_id)`
(cascade delete 및 상위 조회 성능용). `chunk_id`가 이미 `doc_id`를 포함하므로 별도
`UNIQUE(doc_id, ...)` 제약은 불필요.

노드 그래프(JSONB)는 저장하지 않는다 — auto-merge 로직이 `SearchResult`/plain dict 위에서
동작하므로(§5.1) `text`/`child_count`/`parent_id`만으로 충분하다.

### 4.2 Qdrant — payload 확장 (`data-schema.md` §1에 반영 예정)

```
payload
└── parent_chunk_id  : str|null   -- leaf 바로 위 레벨 하나만 가리킴. strategy != "hierarchical"인
                                      문서(기존 recursive/semantic 문서 포함)는 null (하위 호환).
                                      트리 상위 경로는 저장하지 않고, 병합 시 Postgres parent_id를
                                      따라 올라가며 조회한다.
```

### 4.3 `chunk()` 반환 타입 변경

```python
@dataclass
class ParentChunk:
    chunk_id: str
    level: int
    parent_id: str | None
    chunk_index: int
    text: str
    child_count: int
    page_num: int | None
    page_label: str | None

@dataclass
class ChunkResult:
    nodes: list[BaseNode]        # leaf 노드만 (임베딩·검색 대상)
    parents: list[ParentChunk]   # 모든 비-leaf 레벨 노드. strategy != "hierarchical"면 빈 리스트
```

`get_leaf_nodes()`로 leaf를, 나머지 전체 노드(모든 비-leaf 레벨)를 순회하며 `ParentChunk`로
변환한다. `child_count`는 `relationships[NodeRelationship.CHILD]` 원본 길이가 아니라, 그중
`min_chunk_chars` 필터를 통과해 실제로 `nodes`(leaf 리스트)에 남은 자식만 센 값이다 — 필터링
전 개수를 쓰면 §5.1의 비율 계산이 항상 실제보다 낮게 나온다. `child_count=0`이 되는 ancestor는
`parents` 리스트에서 제외한다(§4.1).

`page_num`/`page_label`은 ancestor 노드 자신의 `metadata["page_num"]`/`metadata["page_label"]`을
그대로 읽으면 된다 — 청킹이 `Document` 단위(PDF는 페이지당 1개)로 이뤄지고 서로 다른 `Document`의
텍스트가 한 노드로 합쳐지는 일이 없으므로(`parse.py`), leaf든 ancestor든 노드 하나는 항상 자기
소속 페이지 하나의 값만 갖는다 — 별도 집계 불필요.

`chunk()`의 반환 타입이 `list[BaseNode]`에서 `ChunkResult`로 바뀌므로,
`pipeline/steps/CLAUDE.md`의 파이프라인 계약(`chunk(documents, ...) → list[BaseNode]`)도 구현과
함께 갱신한다.

---

## 5. Auto-Merge 검색 설계

**병합 기준**: "병합 대상"은 임베딩/텍스트 유사도가 아니라 **구조적 인접성**(같은
`parent_chunk_id`)을 의미한다. 서로 다른 ancestor에서 나온 leaf가 의미적으로 비슷하다고 묶이는
일은 없다 — 목적은 검색 결과 압축이 아니라 §1.2의 "문맥 복원"이기 때문이다.

### 5.1 그룹핑 및 병합 (`rag/retriever.py`, 신규 순수 함수, N-level 재귀)

```python
def _auto_merge_parents(
    results: list[SearchResult], threshold: float, max_depth: int
) -> list[SearchResult]:
    from rag_api.infra.postgres import get_parent_chunks

    active, settled = results, []
    for _ in range(max_depth):
        ids = {r.parent_chunk_id for r in active if r.parent_chunk_id}
        if not ids:
            break
        ancestors = get_parent_chunks(list(ids))   # 배치 조회 -> dict[chunk_id, row]

        groups: dict[str, list[SearchResult]] = defaultdict(list)
        passthrough: list[SearchResult] = []
        for r in active:
            if r.parent_chunk_id and r.parent_chunk_id in ancestors:
                groups[r.parent_chunk_id].append(r)
            else:
                passthrough.append(r)   # parent_chunk_id 없음(비활성 문서) 또는 orphan(§5.2)

        merged: list[SearchResult] = []
        any_merged = False
        for pid, children in groups.items():
            a = ancestors[pid]
            if len(children) / a["child_count"] >= threshold:
                r = _build_merged_result(a, children)
                r.parent_chunk_id = a["parent_id"]   # 다음 루프에서 한 레벨 위로 그룹핑되도록 갱신
                merged.append(r)
                any_merged = True
            else:
                merged.extend(children)   # 임계값 미달 -> 이 레벨에서 확정, 다음 레벨 재시도 안 함

        settled.extend(passthrough)
        active = merged
        if not any_merged:
            break

    return settled + active
```

`max_depth`는 `len(cfg.chunk_size) - 1`(비-leaf 레벨 수, `chunk_size`가 리스트일 때)로 설정에서
유도한다. 병합에 실패한
`passthrough` 결과를 `settled`로 분리해두는 것이 핵심 — 그러지 않으면 이미 임계값 미달로 확정된
결과가 다음 레벨에서 엉뚱하게 재시도된다. `ancestors[pid]["child_count"]`는 항상 1 이상이다 —
§4.1에서 `child_count=0`인 ancestor는 애초에 저장하지 않으므로 `len(children) / a["child_count"]`가
0으로 나뉠 일이 없다.

`SearchResult`에 `parent_chunk_id: str | None = None`, `merged: bool = False` 필드를 추가한다.

`_build_merged_result(a, children)`는 `text`(ancestor 텍스트)/`score`(mean)/`parent_chunk_id`
외의 나머지 `SearchResult` 필드는 `children[0]`(같은 문서 소속이므로 아무 하나나 대표)에서
그대로 복사한다 — `doc_id`/`kb_id`/`title`/`source_type`/`source`/`doc_type`/`updated_at`은 같은
문서 안에서 항상 동일하므로 문제없다. `page_num`/`page_label`도 `a["page_num"]`/`a["page_label"]`
(§4.1, ancestor 자신이 속한 페이지 값)을 그대로 채우면 된다 — 청킹이 페이지(Document) 단위로
이뤄져 한 노드가 두 페이지에 걸치는 일이 없으므로 병합 후에도 단일 값으로 정확하다. 유일하게
`chunk_index`만 `None`으로 비운다 — 이건 페이지가 아니라 청크 시퀀스상의 위치라, 병합된 블록이
원래 여러 시퀀스 위치(leaf 여러 개)를 대표해야 해서 단일 값으로 표현할 수 없기 때문이다.

### 5.2 Ancestor 존재 확인 (self-healing)

`get_parent_chunks()` 배치 조회에서 빠진 `parent_chunk_id`(파이프라인 중단 등)는 별도 예외 처리
없이 `passthrough`/`settled`에 남아 원래 개별 결과로 반환된다 — 기존
`_filter_orphaned_chunks()`와 동일한 방어적 패턴.

### 5.3 Threshold / Score

- `retrieval.auto_merge.merge_threshold` (기본 `0.5`) — 매칭 비율이 이 값 이상이면 병합. 모든
  레벨에 동일하게 적용(§1.3).
- 병합된 결과의 `score`는 매칭된 항목 점수의 평균(mean) — 레벨이 올라갈 때마다 그 시점의
  활성 항목들로 재계산된다.
- 병합 후 결과 개수가 `top_k`보다 줄어들 수 있음 — `SearchResultItem`에 `merged: bool` 필드를
  추가해 API 소비자가 구분할 수 있게 한다. 기존 `page_num`/`page_label` 필드는 병합 여부와
  무관하게 그대로 채워진다(§5.1) — 스키마 변경 없이 그대로 재사용.

---

## 6. Settings 확장

```yaml
chunking:
  strategy: "recursive"        # "recursive" | "semantic" | "hierarchical" — 3번째 값 추가
  chunk_overlap: 128           # 기존 필드 그대로 재사용 — leaf(마지막) 레벨에만 적용, root/mid는 0
  chunk_size: 1024             # 기존 필드, 타입을 int -> int | list[int]로 확장.
                                # strategy="recursive"/"semantic"이면 지금처럼 단일 int.
                                # strategy="hierarchical"면 리스트(예: [2048, 512]) — 큰 것부터
                                # 작은 것 순, 마지막 값이 leaf(실제 검색 단위) 크기. 리스트일 때
                                # 최소 2개(=2-level), 3개 이상이면 N-level, 반드시 내림차순

retrieval:
  auto_merge:
    enabled: false               # 별도 스위치 유지 — 청킹(저장)과 병합(검색)은 독립적으로
                                  # 껐다 켤 수 있어야 함(예: 구조는 저장해두고 병합만 잠시 끄기)
    merge_threshold: 0.5          # 0.0 ~ 1.0, 모든 레벨 공통
```

- **on/off는 별도 `enabled` 불리언이 아니라 `chunking.strategy = "hierarchical"` 값 자체다** —
  `strategy`는 이미 `"recursive"`/`"semantic"` 중 하나만 가질 수 있는 단일 값(`Literal`)이라,
  여기에 3번째 값을 추가하면 "semantic이면서 hierarchical도 켜짐" 같은 조합이 애초에
  존재할 수 없다(§1.3의 "semantic/code와 조합 미지원"이 검증 규칙 없이 타입 구조로 보장됨).
  이 프로젝트에 과거 이 자리의 3번째 값이었던 `"document_aware"`가 있었던 전례와도 일치한다
  (다만 의미가 달라져서 새 이름 `"hierarchical"`를 쓴다 — 옛 `document_aware`는 무조건 병합,
  Qdrant 벡터 없는 포인트 저장 방식으로 지금 설계와 다르다).
- **신규 필드가 없다** — `chunking.chunk_size`의 타입을 `int`에서 `int | list[int]`로 확장해서
  그대로 재사용한다. `hierarchical`용 별도 필드(`chunk_sizes` 등)를 만들지 않는다 — 필드
  이름이 하나뿐이라 "단수/복수 중 뭘 써야 하지" 하는 혼동이 없다. `chunk_overlap`도 새 필드
  없이 기존 값을 재사용하되, `_build_hierarchical_parser`가 leaf(마지막) 레벨에만 적용하고
  root/mid는 `overlap=0`으로 분할한다(US-49 후속) — root/mid는 임베딩·검색 대상이 아니라서
  overlap을 줘봐야 Postgres 저장 용량만 늘어난다.
- `chunk_size` 자체의 모양 검증은 **`@field_validator` 하나**로 충분하다 — `strategy`를
  참조할 필요가 없다: 값이 `list`면 "2개 이상, 내림차순"만 확인하고, `int`면 기존 `ge=64,
  le=8192` 범위만 확인한다. `strategy`와 `chunk_size`의 모양이 서로 안 맞는 경우(예:
  `strategy="recursive"`인데 `chunk_size`가 리스트)는 이 validator가 막지 않고, 해당 전략의
  파서(`SentenceSplitter` 등)가 int를 기대하는 자리에 list가 들어가 런타임에 즉시, 크게
  실패한다 — 조용히 잘못된 채로 넘어가는 경우가 없으므로 굳이 `strategy`까지 보는 진짜
  cross-field 검증을 추가하지 않는다. 이 field-level 검증은 전역 `settings.yaml`
  로드(`model_validate`) 경로와 KB 오버라이드 경로 양쪽에서 동일하게 실행된다.
- `chunk_overlap`이 `chunk_size`(leaf 레벨에만 적용, 위 항목) 대비 과도하게 크면(예: leaf
  `chunk_size=60`에 `chunk_overlap=55`) 크래시 없이 통과해 인접 leaf가 거의 통째로 겹치는
  상태로 조용히 색인될 수 있다 — 이 cross-field 검증은
  [US-49](../../../.claude/backlogs/US-49-chunk-overlap-validation.md)로 분리해 구현했다
  (`ChunkingSettings._validate_chunk_overlap`, leaf/int `chunk_size` 대비 15% 캡).
- `chunking.strategy`/`chunking.chunk_size`는 이미 `"chunking."` 접두사 하위 필드라
  `OVERRIDABLE_SETTINGS_PREFIXES`에 이미 포함돼 있다(변경 불필요) — KB마다 다른 문서 성격에
  맞춰 `strategy`를 `"hierarchical"`로, `chunk_size`를 원하는 레벨 구성으로 오버라이드할 수
  있다.
- `retrieval.auto_merge.merge_threshold`는 KB마다 다르게 튜닝할 수 있어야 한다(문서 성격에 따라
  최적값이 다르므로 — §7). 이를 위해 `OVERRIDABLE_SETTINGS_PREFIXES`(`config/settings.py`)에
  `"retrieval."`을 추가해 `chunking.`/`ingestion.`/`dedup.`과 동일하게 KB 단위 오버라이드
  대상에 포함시킨다. 단, 이 접두사 확장은 `retrieval.rerank.api_key`(리랭커 API 자격증명)도
  같이 열어버리므로, 기존 deny-list 메커니즘([kb-settings-override.md](kb-settings-override.md)
  §9.1)으로 `retrieval.rerank.api_key`에 `json_schema_extra={"override": False}`를 명시적으로
  붙여 자격증명은 계속 오버라이드 불가로 막아야 한다 — 이 필드 하나를 빠뜨리면 KB별로 리랭커
  API 키를 노출/변경할 수 있게 되는 구멍이 생긴다.
- `kb_settings_overrides.value`는 `JSONB`라 DB 자체는 어떤 값이든 받아준다([data-schema.md](data-schema.md)
  §2) — 스키마 레벨 제약이 없으므로 검증은 반드시 애플리케이션 코드에서, `infra/postgres.py`의
  `upsert_kb_settings_override()` 호출 **전에** 끝나야 한다: allow-list 확인 → deny-list 확인 →
  `chunk_size`의 `@field_validator`를 명시적으로 호출 → 통과해야 DB에 쓴다. 이 순서를 지키지
  않으면 잘못된 값(예: 오름차순 리스트)이 PATCH 시점엔 그냥 저장되고, 한참 뒤 실제 인제스트가
  돌 때가 돼서야 `HierarchicalNodeParser` 런타임 에러로 뒤늦게 터진다.

---

## 7. 리스크 / 오픈 이슈

구현 방식에 대한 세부 사항(ID 생성 순서, 삽입 순서, settled/active 분리, atomic/code 분기 통합
등)은 해당 섹션(§2, §3.1, §4.3, §5.1, §6)에 이미 반영돼 있다. 여기서는 **구현을 완벽히 해도
사라지지 않는, 이 설계 자체가 내재한 구조적 트레이드오프**만 다룬다.

1. **저장 공간 증가** — 상위 레벨 텍스트는 그 아래 leaf 텍스트를 이미 포함하는 내용이라, 같은
   원문이 레벨 수만큼 중첩 저장된다(root 전체 + 각 parent + 각 leaf). 레벨이 많을수록,
   `chunk_size`(리스트) 값이 클수록 원문 대비 Postgres 저장 용량이 배수로 늘어난다.
2. **검색 지연시간 증가** — auto-merge가 레벨을 하나씩 올라갈 때마다 Postgres 배치 조회를
   추가로 한 번씩 호출한다(§5.1). 레벨이 많을수록 검색 1회당 DB 왕복 횟수가 늘어나는 건
   알고리즘을 완벽히 구현해도 없어지지 않는 구조적 비용이다.
3. **응답 크기를 예측하기 어려움** — 같은 `top_k`로 요청해도 병합 여부에 따라 반환되는 텍스트
   총량이 크게 달라진다(개별 leaf 몇 개 ~ 문서 root 전체). rerank/LLM에 넘어가는 컨텍스트
   토큰 양을 안정적으로 예측하기 어려워진다 — auto-merge가 의도한 동작이지만 운영 시 계속
   신경 써야 하는 비용이다. 외부 리랭커(Jina 등)는 후보 하나당 텍스트 길이 제한이 있는 경우가
   많아, 병합된 결과가 그 제한을 넘으면 리랭크 API 에러 → `fallback_on_error` 경로가 예상보다
   자주 발동할 수 있다.
4. **KB 내 문서 혼재 시 threshold 한계** — `merge_threshold`는 §6에서 KB 단위 오버라이드가
   가능하도록 했으므로 "KB마다 다른 문서 성격(짧은 FAQ성 vs 긴 서술형 매뉴얼)에 맞춰 값을
   다르게 튜닝"하는 문제는 해소된다. 다만 **같은 KB 안에 성격이 다른 문서가 섞여 있으면** 여전히
   하나의 값으로 커버해야 한다(§1.3 — 레벨/문서별 threshold는 미지원) — 일부 문서에서는 과소
   병합(문맥 부족), 다른 문서에서는 과다 병합(무관한 내용 포함)이 구조적으로 발생할 수 있고,
   이건 코드가 아니라 KB 구성(성격이 다른 문서는 KB를 분리) 또는 실측 데이터로만 조정 가능하다.
5. **임계값 경계의 본질적 한계** — 비율이 threshold를 살짝 넘기면(예: 0.5) parent의 절반은
   이번 질의와 무관한 내용이어도 통째로 반환된다. 비율 기반 binary cutoff 자체의 한계라 구현
   정확도와 무관하게 남는다.
6. **`HierarchicalNodeParser`에 대한 지속적 버전 의존** — `AutoMergingRetriever`는 배제했지만
   `HierarchicalNodeParser` 자체는 계속 의존한다. LlamaIndex 메이저 버전업으로 이 클래스의
   동작(특히 `id_func` 전달 방식, `relationships` 구조)이 바뀌면 §3.1 인제스트 로직을 다시
   검증해야 한다 — 한 번 구현하고 끝나는 게 아니라 라이브러리 업그레이드마다 재확인이 필요한
   진행형 리스크다.
7. **설정 변경 시 세대 간 불일치** — KB가 나중에 `chunk_size`(리스트)/`merge_threshold`를 바꾸면, 이미
   인덱싱된 문서(옛 파라미터)와 새로 들어오는 문서(새 파라미터)가 같은 KB 안에서 서로 다른
   크기로 병합된다. 소급 재청킹이 없으므로(§1.3) 이 불일치는 시간이 지나도 스스로 해소되지
   않고, KB 전체를 재인덱싱해야만 정리된다.
8. **재인덱싱 시 짧은 불일치 윈도우** — `chunk_id`가 결정적("{doc_id}:{idx}")이라, 재인덱싱 시
   같은 위치의 ancestor row가 같은 ID로 덮어써진다. `upsert()`(§3.1)에서 새 ancestor를 Postgres에
   커밋한 시점과 Qdrant leaf 청크를 실제로 교체하는 시점 사이에는 짧은 간격이 있어, 그 사이
   검색이 들어오면 옛 Qdrant leaf 결과가 이미 갱신된 새 ancestor 텍스트와 조합될 수 있다.
   Qdrant는 매 업서트마다 완전히 새 UUID를 쓰는 반면(`upsert.py`) ancestor ID는 재사용되기
   때문에 생기는 차이다. 트랜잭션을 묶거나 Qdrant도 매번 새 ID를 쓰게 하면 없앨 수 있지만, 그러면
   leaf가 참조하는 `parent_chunk_id`를 매번 다시 써야 해서 얻는 것보다 복잡도가 커진다 — 재인덱싱
   중 극히 짧은 시간에만 발생하는 낮은 확률의 일시적 불일치로 보고 받아들인다.

---

## 8. 구현 위치 (예정)

| 구성 요소 | 위치 |
|-----------|------|
| Settings 필드 | `src/rag_api/config/settings.py` — `ChunkingSettings.strategy`에 `"hierarchical"` 값 추가, `RetrievalSettings.auto_merge`, `OVERRIDABLE_SETTINGS_PREFIXES`에 `"retrieval."` 추가 + `retrieval.rerank.api_key` deny-list |
| 청킹 (HierarchicalNodeParser) | `src/rag_api/pipeline/steps/chunk.py` |
| Ancestor 저장/조회/삭제 SQL | `src/rag_api/infra/postgres.py` — `save_parent_chunks`, `get_parent_chunks`, `delete_parent_chunks_by_doc` |
| Auto-merge 그룹핑/재귀 병합 로직 | `src/rag_api/rag/retriever.py` |
| Qdrant 업서트 (parent_chunk_id payload) | `src/rag_api/pipeline/steps/upsert.py` |
| 삭제 시 parent_chunks 정리 | `src/rag_api/pipeline/utils/purge.py` |
| `chunk()` 반환 타입 변경에 따른 호출부 수정 (확인된 3곳) | `src/rag_api/pipeline/steps/dedup/chunk_compare.py`(leaf만 사용, `.nodes`), `src/rag_api/defs/ops/ingest_ops.py`, `src/rag_api/pipeline/runner.py` |
| MCP 서버 검색 응답 — 변경 없음(결정: `merged`/`parent_chunk_id` 미노출, REST API만 노출) | `src/rag_api/mcp_server/tools/search.py` |
| 스키마 DDL | `migrations/003_parent_chunks.sql` (신규, 설계 완료·구현 예정) |
| 문서 갱신 | `docs/internal/design/data-schema.md` |

---

## 9. 다음 단계

이 설계에 대한 승인 후 `.claude/backlogs/todo/US-XX-parent-child-chunking.md`를
`_TEMPLATE.md` 형식으로 작성하고, 리뷰 → 승인 → `plans/plan.md` 계획 수립 순서로 진행한다.

---

## 10. 예시 (3-level)

**원문** (`doc_id = a1b2c3d4`, `chunk_size=[600, 200, 60]`처럼 지면상 작은 값으로 예시. 문단
3개 — 하이브리드 검색/리랭킹/임베딩 — 를 가진 하나의 문서 전체가 root):

```
하이브리드 검색은 Dense 벡터와 Sparse 벡터를 결합해 검색 정확도를 높이는 방식이다.
Dense 벡터는 의미 기반 유사도를 포착하고, Sparse 벡터는 키워드 일치를 포착한다.
두 점수는 RRF(Reciprocal Rank Fusion)로 통합되어 최종 순위가 결정된다.

리랭킹은 검색 후보 결과에 대해 정밀한 재순위를 수행하는 단계다.
Jina API 같은 외부 리랭커를 사용하거나, 자체 호스팅한 Cohere 호환 서버를 사용할 수 있다.
리랭커가 비활성화된 경우 RRF 점수를 그대로 최종 순위로 사용한다.

임베딩은 텍스트를 벡터로 변환하는 과정이다.
Dense 임베딩은 Ollama(bge-m3)나 OpenAI 모델을 사용하고, Sparse 임베딩은 BM25 기반 TF 인코더를 사용한다.
두 벡터는 각각 Qdrant에 저장되어 하이브리드 검색에 활용된다.
```

### 10.1 3-level 청킹 결과

```
g0 (level=0, chunk_id="a1b2c3d4:0", parent_id=NULL, child_count=3)  -- 문서 전체(root)
├── p0 (level=1, chunk_id="a1b2c3d4:1", parent_id=g0, child_count=3)  -- "하이브리드 검색" 문단
│   ├── leaf c11 "하이브리드 검색은 Dense 벡터와 Sparse 벡터를 결합해 검색 정확도를 높이는 방식이다."
│   ├── leaf c12 "Dense 벡터는 의미 기반 유사도를 포착하고, Sparse 벡터는 키워드 일치를 포착한다."
│   └── leaf c13 "두 점수는 RRF(Reciprocal Rank Fusion)로 통합되어 최종 순위가 결정된다."
├── p1 (level=1, chunk_id="a1b2c3d4:2", parent_id=g0, child_count=3)  -- "리랭킹" 문단
│   ├── leaf c21 "리랭킹은 검색 후보 결과에 대해 정밀한 재순위를 수행하는 단계다."
│   ├── leaf c22 "Jina API 같은 외부 리랭커를 사용하거나, 자체 호스팅한 Cohere 호환 서버를 사용할 수 있다."
│   └── leaf c23 "리랭커가 비활성화된 경우 RRF 점수를 그대로 최종 순위로 사용한다."
└── p2 (level=1, chunk_id="a1b2c3d4:3", parent_id=g0, child_count=3)  -- "임베딩" 문단
    ├── leaf c31 "임베딩은 텍스트를 벡터로 변환하는 과정이다."
    ├── leaf c32 "Dense 임베딩은 Ollama(bge-m3)나 OpenAI 모델을 사용하고, Sparse 임베딩은 BM25 기반 TF 인코더를 사용한다."
    └── leaf c33 "두 벡터는 각각 Qdrant에 저장되어 하이브리드 검색에 활용된다."
```

### 10.2 저장

`parent_chunks` (Postgres, 자기참조 트리):

| chunk_id | level | parent_id | text | child_count |
|---|---|---|---|---|
| `a1b2c3d4:0` | 0 | NULL | "하이브리드 검색은 ... (전체 3문단)" | 3 |
| `a1b2c3d4:1` | 1 | `a1b2c3d4:0` | "하이브리드 검색은 ... 결정된다." | 3 |
| `a1b2c3d4:2` | 1 | `a1b2c3d4:0` | "리랭킹은 ... 사용한다." | 3 |
| `a1b2c3d4:3` | 1 | `a1b2c3d4:0` | "임베딩은 ... 활용된다." | 3 |

Qdrant payload는 leaf 바로 위 레벨(level 1)만 가리킨다 — g0는 Qdrant에 안 나타남(c22 예시):

```json
{
  "kb_id": "kb-01", "doc_id": "a1b2c3d4", "chunk_index": 4,
  "parent_chunk_id": "a1b2c3d4:2",
  "text": "Jina API 같은 외부 리랭커를 사용하거나, 자체 호스팅한 Cohere 호환 서버를 사용할 수 있다."
}
```

### 10.3 검색 — KB 전체 top_k 경쟁

질의 "하이브리드 검색이랑 RRF 설명해줘", `top_k=5`. `top_k`는 이 문서만이 아니라 **KB 전체
chunk를 점수 순으로 자른 개수**다:

| 순위 | chunk | 소속 | 점수 |
|---|---|---|---|
| 1 | doc_X_chunk | 무관한 다른 문서 | 0.90 |
| 2 | c11 | p0 | 0.88 |
| 3 | c13 | p0 | 0.85 |
| 4 | doc_Y_chunk | 무관한 다른 문서 | 0.80 |
| 5 | c22 | p1 | 0.75 |
| ─── top_k=5 컷라인 ─── | | | |
| 6 | c12 | p0 | 0.62 |
| 7 | c21 | p1 | 0.58 |

p2(임베딩 문단)의 c31/c32/c33은 이 질의와 관련이 거의 없어 애초에 순위표에도 못 오른다(다른
후보들보다 훨씬 낮은 점수) — 검색 결과에 p2 소속 leaf는 하나도 없다.

top_k=5 결과: `[doc_X_chunk(0.90), c11(0.88), c13(0.85), doc_Y_chunk(0.80), c22(0.75)]`

### 10.4 1회차 — leaf(level 2) → parent(level 1)

```
p0: 매칭 [c11, c13] = 2개 / p0의 child_count 3 = 0.67 ≥ 0.5 → p0로 병합
    (병합된 결과의 parent_chunk_id는 p0 자신이 아니라 p0의 부모인 g0로 설정됨 — 병합 대상은
    p0이고, 이 필드는 다음 라운드에서 g0 그룹으로 묶이기 위한 포인터일 뿐 DB 갱신이 아니다)
p1: 매칭 [c22]      = 1개 / p1의 child_count 3 = 0.33 < 0.5 → 병합 안 함 → settled로 확정
p2: 매칭 결과 없음 (애초에 그룹 자체가 안 생김)
doc_X_chunk, doc_Y_chunk: parent_chunk_id 없음 → settled로 확정
```

1회차 후: `settled = [doc_X_chunk, doc_Y_chunk, c22]`, `active = [merged_p0]`
(`merged_p0.parent_chunk_id = "a1b2c3d4:0"`(g0), `score = mean(0.88, 0.85) = 0.865`)

### 10.5 2회차 — parent(level 1) → root(level 0)

`active`에 남은 건 `merged_p0` 하나뿐이다(`c22`는 이미 settled라 여기 안 들어온다 — 이게
§5.1의 settled/active 분리가 하는 일이다).

```
g0: 매칭 [merged_p0] = 1개 / g0의 child_count 3 (p0, p1, p2) = 0.33 < 0.5 → 병합 안 함
```

`any_merged=False`이므로 루프 종료. `merged_p0`는 g0로 승격되지 못하고 그대로 최종 결과에
남는다 — **p1과 p2가 이번 검색에서 매칭되지 않았기 때문에, g0(문서 전체)까지 확장할 근거가
부족하다고 판단한 것**이다. p1이 자기 레벨(10.4)에서 병합에 실패했다는 사실은 g0 판정에
다시 쓰이지 않는다 — g0 비율은 "g0의 직계 자식(p0/p1/p2) 중 몇 개가 이번에 승격됐는가"만 본다.

### 10.6 최종 치환 — 병합 전/후

**병합 전** (top_k=5, 5개):

```python
[
  SearchResult(chunk_id="doc_X_chunk", text="...", score=0.90),
  SearchResult(chunk_id="c11", text="하이브리드 검색은 ... 방식이다.", score=0.88, parent_chunk_id="a1b2c3d4:1"),
  SearchResult(chunk_id="c13", text="두 점수는 RRF(...)로 ... 결정된다.", score=0.85, parent_chunk_id="a1b2c3d4:1"),
  SearchResult(chunk_id="doc_Y_chunk", text="...", score=0.80),
  SearchResult(chunk_id="c22", text="Jina API 같은 ... 수 있다.", score=0.75, parent_chunk_id="a1b2c3d4:2"),
]
```

**병합 후** (4개 — c11/c13이 p0 텍스트 하나로 치환됐지만 g0까지는 확장되지 않음, c22는 임계값
미달로 원형 유지):

```python
[
  SearchResult(chunk_id="doc_X_chunk", text="...", score=0.90),
  SearchResult(chunk_id="a1b2c3d4:1", text="하이브리드 검색은 Dense 벡터와 Sparse 벡터를 결합해 "
      "검색 정확도를 높이는 방식이다. Dense 벡터는 의미 기반 유사도를 포착하고, Sparse 벡터는 "
      "키워드 일치를 포착한다. 두 점수는 RRF(Reciprocal Rank Fusion)로 통합되어 최종 순위가 "
      "결정된다.", score=0.865, merged=True, parent_chunk_id="a1b2c3d4:0"),
  SearchResult(chunk_id="doc_Y_chunk", text="...", score=0.80),
  SearchResult(chunk_id="c22", text="Jina API 같은 ... 수 있다.", score=0.75, parent_chunk_id="a1b2c3d4:2"),
]
```

정리하면: leaf 3개(c11, c12, c13) 중 2개가 걸려 "하이브리드 검색" 문단(p0) 하나로 압축됐고,
그 위 문서 전체(g0, 리랭킹·임베딩 문단까지 포함)로는 확장되지 않았다 — 이 질의가 문서 전체
주제가 아니라 그중 한 섹션에만 해당한다는 걸 정확히 반영한 결과다.
