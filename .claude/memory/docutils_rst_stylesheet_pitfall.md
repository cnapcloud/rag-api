---
name: docutils-rst-stylesheet-pitfall
description: docutils publish_string()+html5_polyglot embeds default CSS as inline <style> text that tag-stripping doesn't remove — use publish_parts()['body']/['title'] instead
metadata:
  type: project
---

`RstReader`(`src/rag_api/pipeline/step/parser/rst.py`, US-42)를 R2R의 `rst_parser.py` 방식
그대로(`docutils.core.publish_string()` + html5_polyglot writer → 정규식으로 태그 제거) 포팅했더니
결과 텍스트에 docutils 기본 스타일시트 전체(`font-family`, `margin` 등 수백 단어 분량의 CSS)가
그대로 섞여 나왔다. `publish_string()`은 `<head>`에 `<style>` 블록으로 CSS를 임베드한 완전한
HTML 문서를 반환하는데, `<[^>]+>` 태그 제거 정규식은 태그만 지울 뿐 `<style>` **내용**은
지우지 않기 때문이다. R2R 원본도 동일한 결함을 갖고 있었을 것으로 보인다(같은 방식).

**How to apply**: docutils로 RST/텍스트 마크업을 HTML화해 태그만 벗겨내려는 경우
`publish_string()`(완전한 문서) 대신 `publish_parts()`를 쓰고 `body`(+필요하면 `title`) 키만
사용할 것 — 이 경로는 스타일시트/head를 포함하지 않는다. 다른 포맷(예: 향후 org-mode 등)에
docutils나 유사 "마크업→HTML→태그제거" 파이프라인을 다시 쓸 때도 같은 함정을 확인할 것.

관련: [파서 패키지 구조화(US-42)](../backlogs/US-42-parser-package-restructure.md)
