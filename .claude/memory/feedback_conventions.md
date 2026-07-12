---
name: feedback-conventions
description: 테스트 작성 시 비직관적인 함정 (rules 문서에 없는 내용만)
metadata:
  node_type: memory
  type: feedback
  originSessionId: 8d64a12e-8ccb-46d4-9977-4b334c0ec4a7
---

**SentenceSplitter 테스트 텍스트 주의**: `"A" * N`처럼 공백 없는 연속 문자는 단일 청크로 반환됨. 반드시 `"word " * N` 또는 실제 문장 사용.

**Why:** SentenceSplitter는 문장/단어 경계로 분할하므로 공백이 없으면 분할 불가.

**How to apply:** chunk Op 테스트 작성 시 `"sample text " * N` + 작은 chunk_size 조합 사용.
