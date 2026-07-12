# .claude/rules/ — AI 작업 워크플로우

**목적**: 코딩 스타일이 아닌, AI가 작업하는 방식에 대한 제약.

---

## 규칙 목록

### 0. 진행 상황 파악 (`conventions/00-progress-tracking.md`)
세션 시작 시 `backlogs/backlog.md`와 `plans/plan.md` 인덱스를 먼저 읽어 현재 상태 파악.
작업 시작/완료 시 해당 행의 status 즉시 업데이트.

### 1. 설정 싱글턴 우선 (`00-hard-rules.md`)
`get_settings()` 우회 금지. 설정값 하드코딩 금지.

### 2. Import 경로 (`conventions/01-import-paths.md`)
`from src.` 형태 금지. `rag_api`는 editable install되어 있어 `PYTHONPATH` 불필요.

### 3. 인프라 Mock (`conventions/02-testing.md`)
테스트에서 실제 Redis/Qdrant/MinIO 연결 생성 금지.

### 4. Op 순수 함수
파이프라인 Op은 Dagster context 없이 동작해야 함.

### 5. 파일 확인 후 수정
`infra/` 파일은 수정 전 내용 확인 필수 (복붙 사고 전례).

### 6. 예외 처리 (`conventions/05-exception-handling.md`)
레이어별 exception 타입 구분. 메시지 영어. silent swallow 금지. `from e` chaining 필수.

### 7. 로깅 (`conventions/06-logging.md`)
모듈별 `logging.getLogger(__name__)` 사용. `setup_logging()`이 `main.py`에서 먼저 호출됨.
레벨은 settings에서. 영어, `%s` 포맷, 컨텍스트 포함 필수.

### 8. 추적성 (`conventions/07-traceability.md`)
prd.md ↔ design 문서 ↔ backlog ↔ plan을 파일 상단 고정 링크와 파일명 키워드로 연결.
새 backlog/plan/design 작성 시, 또는 backlog를 `done`으로 전환할 때 반드시 적용. 세션마다 읽는
0과 달리 실제로 이 문서들을 쓸 때만 열어보면 된다.

### 9. 스펙 기반 개발 절차 (루트 `spec-driven-ai-development.md`)
0과 8의 상세 규칙을 실제 워크플로우 순서(세션 시작 → backlog 작성 → design 작성 → done 전환)로
정리한 사람/AI 공통 진입 문서. 새 작업을 시작할 때 가장 먼저 읽는다. `.claude/rules/` 밖(루트)에
있는 이유: 사람 기여자도 같은 절차를 보게 하기 위함 — 내용을 복제하지 않고 이 한 곳만 유지한다.

---

## 워크플로우: 새 기능 추가

```
0. backlogs/backlog.md + plans/plan.md 읽어 진행 상황 파악
1. 해당 backlog 행 status → in-progress로 변경
2. conventions/ 관련 문서 읽기
3. 기존 Op 패턴 참조 (pipeline/ops/ 기존 파일)
4. 테스트 먼저 작성 → 구현 → 테스트 통과 확인
5. backlog/plan 인덱스 status → done으로 업데이트
6. 학습 내용 memory/MEMORY.md에 저장
```

---

## 참조

- `conventions/` — 코딩 규칙 상세
- `backlogs/backlog.md` — 백로그 항목 및 완료 현황
- `plans/plan.md` — 구현 계획 및 완료 현황
- `CLAUDE.md` (루트) — 빠른 참조
- `docs/internal/known-issues.md` — 알려진 이슈 전체 목록. 발견한 이슈는 CLAUDE.md가 아니라
  이 문서에 정해진 양식(상태/발견일/심각도 표 + 증상/원인/현재 대안/미해결)으로 기록한다.
