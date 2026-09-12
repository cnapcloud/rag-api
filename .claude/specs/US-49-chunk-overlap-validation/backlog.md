# US-49: chunk_overlap - chunk_size cross-field 검증 추가

**상태**: done

> 설계: [parent-child-chunking.md §6](../../../docs/internal/design/parent-child-chunking.md#6-settings-확장)

## 목적

`HierarchicalNodeParser`는 root부터 leaf까지 모든 레벨에 동일한 `chunk_overlap` 값을 적용한다
(레벨별로 다른 값을 주는 기능 없음 — 소스로 확인, US-03 오픈 이슈였던 항목의 답). 그런데
`chunk_overlap`이 가장 작은 레벨(leaf) `chunk_size`에 가까우면(예: leaf=60, overlap=55)
`SentenceSplitter`가 크래시하지 않고 그대로 통과해, 인접 leaf끼리 거의 통째로 겹치는 상태로
조용히 색인된다. 현재 `ChunkingSettings`에는 이 조합을 막는 검증이 없다
(`config/settings.py:97` 주석 "cross-field: chunk_overlap < chunk_size ... 이번 US 범위 밖"이
가리키던 미해결 항목).

같은 원인(`chunk_size: Annotated[int, Field(ge=64, le=8192)] | list[int]`에서 `ge`/`le`가 int
분기에만 걸리고 list 항목에는 전혀 적용되지 않음)으로, `chunk_size`가 `list`일 때 각 항목의
범위 자체도 검증되지 않는다(`_validate_chunk_size`는 "2개 이상, 내림차순"만 확인) — 예:
`chunk_size=[999999, 5]`도 현재는 그대로 통과한다. 두 문제 모두 같은 `ChunkingSettings`
검증 로직을 건드리므로 이 US에서 함께 처리한다.

## 범위

- `ChunkingSettings.chunk_overlap`에 `@field_validator` 추가 — `chunk_size`가 `list`면
  `min(chunk_size)`, `int`면 그 값 자체를 기준으로 `chunk_overlap > 기준값 * 0.15`이면 거부
- `ValidationInfo.data`로 이미 검증된 `chunk_size`를 참조 (필드 선언 순서상 `chunk_size`가
  `chunk_overlap`보다 앞에 있어 가능 — 확인됨)
- `_validate_chunk_size`(`chunk_size`가 `list`인 경우)에 항목별 범위 검증 추가 — 기존 int
  분기와 동일한 `ge=64, le=8192`를 각 항목에 적용
- 전역 `settings.yaml` 로드(`model_validate`) 경로와 KB 오버라이드 경로 양쪽에 동일 적용

## 비범위

- 레벨별로 서로 다른 `chunk_overlap` 지원 — `HierarchicalNodeParser` 자체가 단일 값만 받으므로
  대상 아님
- `chunk_size`/`strategy` 모양 불일치 검증 — 기존 `_validate_chunk_size`가 이미 처리 (해당
  없음, 이번 US는 `chunk_overlap`-`chunk_size` 조합만 다룸)

## 완료 기준

- [x] `chunk_size`가 `list`일 때 `min(chunk_size) * 0.15`를 초과하는 `chunk_overlap`이 거부된다
- [x] `chunk_size`가 `int`일 때도 동일 캡이 적용된다 (기존 기본값 `1024`/`128`=12.5%는 통과)
- [x] `chunk_size`가 `list`일 때 각 항목이 `64~8192` 범위를 벗어나면 거부된다 (기존 int 분기와
      동일 기준, 예: `[999999, 5]` 거부)
- [x] KB 오버라이드 경로(`PATCH` 설정)에서도 두 검증이 모두 걸린다
- [x] 관련 테스트 전체 통과

## 의존성

- US-03 — `chunk_size`가 `int | list[int]`로 확장되어 있어야 이 검증이 의미를 가짐

## 오픈 이슈

- 캡 비율 15%의 근거: LlamaIndex `HierarchicalNodeParser.from_defaults()` 자체 기본값
  (`chunk_overlap=20`, 기본 leaf `chunk_size=128` 기준 15.6%) + 업계 관례(10~20%, NVIDIA
  자체 실측 최적값 15%). 정확한 % 자체는 임의 조정 가능한 값이므로 실측 후 바뀔 수 있음.
- 항목 범위 `64~8192`는 기존 int 분기 값을 그대로 재사용한 것 — leaf만 따로 더 좁은 상한
  (예: 512, flat chunking 스윗스팟과 역할이 겹치지 않게)을 둘지는 이번 US 범위 밖으로 남겨둔다
  (전체 항목 동일 기준 vs 레벨별 다른 기준은 별도 결정 필요).
