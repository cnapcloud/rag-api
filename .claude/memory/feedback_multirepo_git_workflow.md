---
name: feedback-multirepo-git-workflow
description: rag-api/rag-ent-api/rag-admin patch→main 반복 머지 워크플로우에서 지켜야 할 git 작업 습관
metadata:
  type: feedback
---

**merge 후 즉시 patch로 되돌아가기**: `patch`를 `main`에 머지하고 push한 직후, 반드시 `git checkout patch`로 돌아간다. `main`에 그대로 머문 채 다음 변경을 커밋하면 `patch`에는 없는 커밋이 `main`에만 생겨 브랜치가 갈라지고, 다음 `patch`→`main` 머지에서 불필요한 충돌이 난다.

**Why:** 이 세션에서 main에 머문 채로 액션 버전 업그레이드를 커밋(`d065a51`)했다가, patch에는 없는 내용이라 다음 patch→main 머지 때 `astral-sh/setup-uv` 줄에서 충돌이 났고 별도로 cherry-pick까지 해야 했음.

**How to apply:** `git merge patch -m "merge: patch into main" && git push origin main` 다음 줄에 항상 `git checkout patch`를 붙인다. 커밋 전에는 `git branch --show-current`로 확인.

---

**여러 저장소를 오갈 때는 `git -C <path>`를 쓰고 persisted cwd에 의존하지 않기**: Bash 툴의 작업 디렉토리는 명령 간에 유지되므로, 앞선 명령에서 `cd rag-admin`을 했다면 다음 명령이 무심코 rag-api가 아니라 rag-admin에서 실행된다.

**Why:** 이 세션에서 rag-api의 patch에 cherry-pick하려던 명령이 persisted cwd 때문에 실제로는 rag-admin에서 실행되어, 관련 없는 옛 커밋(`e59074b`)이 cherry-pick되며 충돌이 났음. `git cherry-pick --abort`로 복구해야 했음.

**How to apply:** rag-api/rag-ent-api/rag-admin/aiops 등 여러 저장소를 오갈 때는 매 명령에 `git -C /Users/lemon/Devel/ai/<repo>`를 명시한다. `cd` 후 다음 명령을 실행하기 전에는 `pwd`로 현재 위치를 재확인한다.

---

**작업 대상 저장소가 명확하면(예: rag-admin 프론트엔드 버그) 다른 저장소 조사를 위해 subagent를 띄우지 않기**: rag-admin 프론트엔드 문제를 백엔드(rag-api) 스키마까지 파고들며 Agent 서브에이전트로 조사하려다 두 번 연속 거부당함.

**Why:** 사용자가 "rag-admin만 보면 되는데,, 백엔든 볼필요가 없는데"라고 직접 지적. 프론트엔드 버그는 대개 프론트 코드 내부에 이미 같은 문제를 처리하는 기존 패턴(예: `isUrl()` 헬퍼)이 있으므로, 백엔드 스키마를 추측/확인하러 갈 필요 없이 grep으로 같은 저장소 안에서 기존 패턴을 먼저 찾는 게 맞았음.

**How to apply:** 특정 저장소 범위가 분명한 버그/요청은 그 저장소 안에서 직접 Read/Grep으로 먼저 해결을 시도한다. 여러 저장소를 넘나드는 진짜 원인 조사가 필요할 때만, 그리고 가능하면 사용자에게 먼저 확인하고 나서 Agent를 쓴다.
