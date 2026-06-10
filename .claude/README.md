# .claude/ — AI 개발 가이드

**목적**: Claude Code가 이 프로젝트를 올바르게 이해하고 작업하기 위한 컨텍스트 문서.

---

## 폴더 구조

```
.claude/
├── README.md                        ← 이 파일
├── conventions/                     ← 코딩 방식
│   ├── 00-tech-stack.md             # 기술 스택 전체
│   ├── 01-import-paths.md           # import 경로 규칙
│   ├── 02-testing.md                # 테스트 패턴
│   ├── 03-pipeline-ops.md           # 파이프라인 Op 작성 규칙
│   ├── 04-infra-layer.md            # 인프라 클라이언트 규칙
│   └── 05-exception-handling.md     # 예외 처리 규칙
├── rules/                           ← AI 작업 워크플로우
│   ├── README.md                    # 규칙 요약
│   └── 01-hard-rules.md             # 절대 금지 사항
├── backlog/                         ← 사용자 요구 기능 (User Story만 기록)
│   └── US-{index}-{slug}.md         # 파일당 하나의 User Story
├── plan/                            ← 구현 계획 (backlog 기반)
│   └── {index}-{slug}.md            # 파일당 하나의 구현 계획
└── memory/                          ← Claude Code 자동 저장 학습 내용
    └── MEMORY.md
```

### backlog/ 규칙

- **User Story만** 기록. 구현 상세, 파일 목록, 코드 스니펫 금지.
- 파일명: `US-{두자리숫자}-{기능-슬러그}.md`
- 각 파일은 단일 User Story (Who / What / Why 구조).
- 완료된 Story는 파일 상단에 `status: done` 표기 후 유지.

### plan/ 규칙

- backlog User Story의 **구현 계획**. 파일명 인덱스는 대응하는 US 번호 사용.
- 설계 결정, 파일 목록, 구현 순서, API 시그니처 포함.
- 구현 완료 후 `status: done` 표기.

---

## 언제 읽어야 하는가

### 코드 작성 전
- 새 Op / 라우터 작성 → `conventions/03-pipeline-ops.md`
- 인프라 클라이언트 수정 → `conventions/04-infra-layer.md`
- import 경로 불확실 → `conventions/01-import-paths.md`

### 계획 수립 전
- 무엇을 만들어야 하는지 → `backlog/`
- 구현 방법 → `plan/`
- 하지 말아야 할 것 → `rules/01-hard-rules.md`

---

## CLAUDE.md와의 관계

```
CLAUDE.md (루트)
└── 빠른 참조 (명령어, 파이프라인 흐름, API 목록)
    ↓
.claude/conventions/
└── 세부 코딩 규칙
    ↓
.claude/rules/
└── AI 워크플로우 제약
    ↓
.claude/backlog/ + plan/
└── 무엇을 / 어떻게 만들 것인가
```

---

## Git 전략

`.claude/` 폴더는 커밋에 포함. 팀 전체가 동일한 AI 가이드라인을 공유.
`memory/` 내용도 커밋하여 세션 간 학습 내용 유지.
