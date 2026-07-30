# Plan: US-03 Parent-Child 청킹 & Auto-Merge 검색

## Context

설계 근거·스키마 전체·알고리즘 상세는 [parent-child-chunking.md](../../docs/internal/design/parent-child-chunking.md)에
있다 — 이 문서는 "왜"가 아니라 "어떤 순서로, 어느 파일을 어떻게" 구현하는지만 다룬다.

의존 순서: Settings → 마이그레이션 → infra/postgres.py → chunk.py → upsert.py → 호출부 수정 →
purge.py → retriever.py → API 응답 → 문서 갱신.

---

## 1. Settings (`src/rag_api/config/settings.py`)

```python
ChunkStrategy = Literal["recursive", "semantic", "hierarchical"]   # 3번째 값 추가 (pipeline/steps/chunk.py)


class ChunkingSettings(BaseModel):
    strategy: ChunkStrategy = Field(default="recursive", ...)   # 기존 필드, 타입만 확장
    ...
    # chunk_size: 기존 필드, 타입을 int -> int | list[int]로 확장. 신규 필드 없음.
    # strategy="recursive"/"semantic"이면 지금처럼 단일 int, "hierarchical"면 리스트.
    chunk_size: int | list[int] = Field(default=1024, ...)

    @field_validator("chunk_size")
    @classmethod
    def _validate_chunk_size(cls, v: int | list[int]) -> int | list[int]:
        if isinstance(v, list):
            if len(v) < 2:
                raise ValueError("chunk_size list must have at least 2 levels")
            if any(v[i] <= v[i + 1] for i in range(len(v) - 1)):
                raise ValueError("chunk_size list must be strictly descending")
        # int인 경우는 기존 ge=64, le=8192 range validator 그대로 유지
        return v
    # strategy와 chunk_size 모양(int/list)이 안 맞는 조합은 여기서 막지 않는다 — 해당 전략의
    # 파서가 런타임에 즉시 실패하므로 cross-field validator 불필요(design §6)


class AutoMergeSettings(BaseModel):
    enabled: bool = False
    merge_threshold: float = Field(default=0.5, ge=0.0, le=1.0)


class RetrievalSettings(BaseModel):
    ...
    auto_merge: AutoMergeSettings = Field(default_factory=AutoMergeSettings)
```

`OVERRIDABLE_SETTINGS_PREFIXES`에 `"retrieval."` 추가:

```python
OVERRIDABLE_SETTINGS_PREFIXES = ("ingestion.", "chunking.", "dedup.", "retrieval.")
```

`RerankerSettings.api_key` 필드에 deny-list 플래그 추가(design §6):

```python
api_key: str = Field(default="", json_schema_extra={"override": False})
```

`_field_validator`가 `chunk_size` 자체에 붙어 있으므로, KB 오버라이드 PATCH 경로(§4)에서
`TypeAdapter(list[int])` 대신 이 필드 타입을 직접 재사용해 검증한다 — 새 검증 로직을 따로
만들지 않는다.

`settings.yaml` / `docker/settings.yaml`에 기본값 블록 추가:

```yaml
chunking:
  strategy: "recursive"        # "recursive" | "semantic" | "hierarchical"
  chunk_overlap: 128           # 기존 필드 재사용, 모든 레벨 공통
  chunk_size: 1024             # 기존 필드 — strategy="hierarchical"면 [2048, 512]처럼 리스트로

retrieval:
  auto_merge:
    enabled: false
    merge_threshold: 0.5
```

---

## 2. 마이그레이션 (`migrations/003_parent_chunks.sql`)

```sql
CREATE TABLE IF NOT EXISTS parent_chunks (
    chunk_id     TEXT         PRIMARY KEY,
    doc_id       TEXT         NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    kb_id        TEXT         NOT NULL REFERENCES knowledge_bases(kb_id) ON DELETE CASCADE,
    level        SMALLINT     NOT NULL,
    parent_id    TEXT         REFERENCES parent_chunks(chunk_id) ON DELETE CASCADE,
    chunk_index  INTEGER      NOT NULL,
    text         TEXT         NOT NULL,
    child_count  INTEGER      NOT NULL,
    page_num     INTEGER,
    page_label   TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parent_chunks_doc ON parent_chunks (doc_id);
CREATE INDEX IF NOT EXISTS idx_parent_chunks_parent ON parent_chunks (parent_id);
```

(design §4.1 그대로 — `child_count`는 필터링 후 값만 저장하므로 `NOT NULL`에 `DEFAULT` 없음,
0인 행 자체를 안 만듦)

---

## 3. `src/rag_api/infra/postgres.py`

`simhash_bands`류 함수와 동일한 스타일로 3개 추가:

```python
def save_parent_chunks(parents: list[ParentChunk]) -> None:
    """root(level 0)부터 순서대로 insert — 자기참조 FK 때문에 parent가 먼저 존재해야 함."""
    ...

def get_parent_chunks(chunk_ids: list[str]) -> dict[str, dict]:
    """배치 조회 -> {chunk_id: row}. get_existing_doc_ids와 동일한 배치 패턴."""
    ...

def delete_parent_chunks_by_doc(doc_id: str) -> None:
    """delete_simhash_bands/delete_minhash_bands와 동일 위치에서 호출됨(purge.py)."""
    ...
```

`ParentChunk`는 `pipeline/steps/chunk.py`에 정의(§4).

---

## 4. `src/rag_api/pipeline/steps/chunk.py`

### 4.1 데이터클래스 (design §4.3)

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
    nodes: list[BaseNode]
    parents: list[ParentChunk]
```

### 4.2 `chunk()` 분기 추가

`cfg.strategy == "hierarchical"`이고 텍스트 문서인 경우(atomic/code 경로는 그대로 유지):

1. `id_func`로 `f"{doc_id}:{next(counter)}"` 형태의 전역 카운터 발급 (문서 하나당 counter 하나 공유)
2. `HierarchicalNodeParser.from_defaults(chunk_sizes=cfg.chunk_size, chunk_overlap=cfg.chunk_overlap, ...)`로 분할
   — `cfg.chunk_size`는 이 시점 리스트, HierarchicalNodeParser 쪽 파라미터명(`chunk_sizes`,
   복수)과 다르지만 우리 설정 필드명은 `chunk_size`(단수)로 통일
   — `chunk_overlap`은 기존 `ChunkingSettings.chunk_overlap` 그대로 재사용(신규 필드 아님)
   — **실제 구현 시 `chunk_overlap`이 레벨별로 다르게 지정 가능한지 시그니처 확인**(design §7)
3. `get_leaf_nodes(all_nodes)` → leaf, 나머지 → ancestor 후보
4. 기존 `min_chunk_chars` 필터를 leaf에 적용(변경 없음)
5. 필터 통과한 leaf만으로 각 ancestor의 `child_count` 계산 — `relationships[CHILD]` 원본 길이가
   아니라 **필터 후 남은 자식 수**를 센다. `child_count == 0`인 ancestor는 `parents`에서 제외
6. 각 leaf의 `relationships[PARENT].node_id`를 읽어 `leaf.metadata["parent_chunk_id"]`에 기록
7. 각 ancestor의 `page_num`/`page_label`은 자기 자신의 metadata에서 직접 읽음(페이지당 Document
   구조라 leaf와 동일한 단일 값 — 별도 집계 불필요, design 대화 참고)
8. `ChunkResult(nodes=leaf_list, parents=parent_chunk_list)` 반환
9. `strategy`가 `"recursive"`/`"semantic"`이면 기존과 동일하게 `ChunkResult(nodes=..., parents=[])`
   반환 (호출부가 `.nodes`만 쓰면 기존 동작과 100% 동일)

### 4.3 `pipeline/steps/CLAUDE.md` 계약 갱신

`chunk(documents, ...) → list[BaseNode]`를 `chunk(documents, ...) → ChunkResult`로 수정.

---

## 5. `src/rag_api/pipeline/steps/upsert.py`

`upsert()` 시그니처에 `parents: list[ParentChunk]` 인자 추가, 처리 순서:

1. `delete_parent_chunks_by_doc(doc_id)`
2. `save_parent_chunks(parents)` (parents가 빈 리스트면 no-op)
3. 기존 Qdrant `delete_chunks_by_doc_id` + `upsert_chunks` — payload에 `parent_chunk_id` 필드
   추가(`meta.get("parent_chunk_id")`, 없으면 `None`)

1·2번이 3번보다 먼저 실행되어야 함(design §3.1).

---

## 6. 호출부 수정 (확인된 3곳)

| 파일 | 변경 |
|---|---|
| `src/rag_api/pipeline/steps/dedup/chunk_compare.py:80` | `nodes = chunk(documents, kb_id=kb_id)` → `nodes = chunk(documents, kb_id=kb_id).nodes` |
| `src/rag_api/defs/ops/ingest_ops.py:123` | `chunk(...)` → `chunk_result = chunk(...)`, `chunk_result.nodes`는 `embed()`로, `chunk_result.parents`는 `upsert()`로 전달 |
| `src/rag_api/pipeline/runner.py` | 위와 동일하게 non-Dagster 실행 경로 수정 |

---

## 7. `src/rag_api/pipeline/utils/purge.py`

`delete_simhash_bands`/`delete_minhash_bands`와 같은 자리에 추가:

```python
_run(delete_parent_chunks_by_doc, doc_id)
```

soft delete 경로(`include_chunks=False`로 호출되는 곳)에서도 실행되는지 확인 — dedup bands와
동일하게 무조건 호출.

---

## 8. `src/rag_api/rag/retriever.py`

### 8.1 `SearchResult`에 필드 추가

```python
parent_chunk_id: str | None = None
merged: bool = False
```

`_node_to_result()`에서 `meta.get("parent_chunk_id")`를 `parent_chunk_id`에 채움.

### 8.2 `_auto_merge_parents()` 신규 함수 (design §5.1 코드 그대로)

```python
def _auto_merge_parents(results: list[SearchResult], threshold: float, max_depth: int) -> list[SearchResult]:
    from rag_api.infra.postgres import get_parent_chunks

    active, settled = results, []
    for _ in range(max_depth):
        ids = {r.parent_chunk_id for r in active if r.parent_chunk_id}
        if not ids:
            break
        ancestors = get_parent_chunks(list(ids))

        groups: dict[str, list[SearchResult]] = defaultdict(list)
        passthrough: list[SearchResult] = []
        for r in active:
            if r.parent_chunk_id and r.parent_chunk_id in ancestors:
                groups[r.parent_chunk_id].append(r)
            else:
                passthrough.append(r)

        merged, any_merged = [], False
        for pid, children in groups.items():
            a = ancestors[pid]
            if len(children) / a["child_count"] >= threshold:
                r = _build_merged_result(a, children)
                r.parent_chunk_id = a["parent_id"]
                merged.append(r)
                any_merged = True
            else:
                merged.extend(children)

        settled.extend(passthrough)
        active = merged
        if not any_merged:
            break

    return settled + active


def _build_merged_result(a: dict, children: list[SearchResult]) -> SearchResult:
    base = children[0]
    return SearchResult(
        chunk_id=a["chunk_id"], kb_id=base.kb_id, doc_id=base.doc_id, doc_type=base.doc_type,
        title=base.title, chunk_index=None, page_num=a["page_num"], page_label=a["page_label"],
        text=a["text"], score=sum(c.score for c in children) / len(children),
        rerank_score=None, updated_at=base.updated_at, source_type=base.source_type,
        source=base.source, parent_chunk_id=None, merged=True,
    )
```

`max_depth = len(settings.chunking.chunk_size) - 1` (이 시점 `chunk_size`는 리스트).

### 8.3 `_search_kb()`에 통합

`index.as_retriever().retrieve(query)` 결과를 `SearchResult` 리스트로 만든 직후,
`auto_merge.enabled`면 `_auto_merge_parents(results, cfg.retrieval.auto_merge.merge_threshold, max_depth)` 호출 —
`_filter_orphaned_chunks()`보다 먼저, KB 단위로 수행(멀티 KB `rrf_merge` 이전).

---

## 9. `src/rag_api/api/routers/search.py`

`SearchResultItem`에 `merged: bool = False` 필드 추가, `search()` 응답 조립부에 `merged=r.merged` 추가.
`parent_chunk_id`는 REST 응답에 노출(§8 결정), MCP(`mcp_server/tools/search.py`)는 변경 없음.

---

## 10. 문서 갱신

`docs/internal/design/data-schema.md` §1(Qdrant payload)에 `parent_chunk_id` 필드 추가,
§2에 `parent_chunks` 테이블 섹션 추가.

---

## 11. 테스트

- `chunk.py`: `strategy="hierarchical"`로 3-level 문서 청킹 → leaf/ancestor 개수, `parent_chunk_id`
  체인, `child_count`(필터 반영) 단위 테스트
- `retriever.py`: `_auto_merge_parents()` — 2-level 병합/미병합, 3-level 캐스케이드(§10.6 예시
  수치 그대로 재현), orphan(parent row 없음) self-healing 단위 테스트
- `purge.py`: soft/hard delete 후 `parent_chunks` 행 삭제 확인
- `dedup/chunk_compare.py`: 기존 테스트가 `chunk().nodes` 변경 후에도 통과하는지
- KB 오버라이드: `chunk_size`에 오름차순 리스트 PATCH 시 거부, `retrieval.rerank.api_key` PATCH 시 거부

## 검증

```bash
make test
.venv/bin/ruff check src/
```
