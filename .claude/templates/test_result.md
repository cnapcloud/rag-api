# US-NN: <제목> — 검증 결과

> 담당: `validator` · spec 워크플로우 4단계(최종) · 템플릿: `.claude/templates/test_result.md`

**대상**: [spec.md](spec.md) / [design.md](design.md) / [task.md](task.md)

## 완료 기준 검증

| AC | 검증 방법 | 결과 | 비고 |
|---|---|---|---|
| <AC> | `<uv run pytest 명령>` 또는 수동 확인 절차 | <PASS/FAIL> | <FAIL이면 [구현]/[설계] + 이유> |

## architecture 재검증

- [ ] design.md에 적힌 레이어/파일이 실제 코드 위치와 일치한다
- [ ] 역방향 참조(하위 레이어가 상위 레이어를 참조)가 생기지 않았다
- [ ] design.md/task.md 범위에 없는 파일이 추가로 수정되지 않았다 (범위 이탈 여부)

<불일치 내용 (없으면 "(불일치 없음)")>

## 결론

- [ ] 전체 AC 통과 — spec.md **상태**를 `done`으로 전환 가능
- [ ] 일부 실패 — 아래 실패 목록을 command가 사용자에게 전달

<실패 목록 (있으면): AC ID + 유형(`[구현]`/`[설계]`) + 이유. 없으면 이 줄 생략>
