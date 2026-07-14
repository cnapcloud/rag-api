# Git Merge — main 병합 커밋 메시지

목적: `build-push.yml`은 워크플로 실행 제목을 트리거 커밋 메시지 첫 줄로 자동 생성한다
(`run-name` 미지정). `git merge -m "Merge branch 'patch'"`처럼 제목을 고정 문자열로 쓰면
Actions 실행 목록이 전부 "Merge branch 'patch'"로만 보여 구분이 안 된다.

## 규칙

`patch` (또는 다른 브랜치)를 `main`에 머지할 때, 병합 커밋 메시지 첫 줄은 이번에 합쳐지는
커밋들의 내용을 요약해서 쓴다. `Merge branch 'patch'` 같은 git 기본 문구를 그대로 쓰지 않는다.

```bash
# 병합 대상 커밋 로그 확인
git log origin/main..patch --oneline

# 커밋 메시지에 요약 반영
git merge patch -m "$(cat <<'EOF'
merge: patch into main — <합쳐지는 커밋 요약>

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- 합쳐지는 커밋이 1개면 그 커밋 메시지를 그대로(또는 축약해) 제목으로 사용.
- 여러 개면 가장 의미 있는 변경 위주로 한 줄 요약(예:
  `merge: patch into main (lint fix, docs update)`).
- 이 저장소 과거 이력의 `merge: patch into main (US-08, US-10/11, ...)` 스타일을 따른다.
