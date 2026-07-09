---
name: html-extraction-corpus-boilerplate-rejected
description: corpus 빈도 기반 사이트 boilerplate 자동 탐지를 검토 후 폐기한 이유 — 스트리밍 ingestion과 cold-start 비호환
metadata:
  type: project
---

`docs/internal/design/html-extraction.md` 초안에서 "같은 connector의 여러 문서를 가로질러 줄
단위 등장 빈도를 집계해 일정 비율 이상 반복되는 줄을 boilerplate로 자동 판정"하는 방식
(connector_boilerplate_lines 테이블 + Dagster asset)을 설계했으나, 사용자가 지적해 폐기했다
(2026-07-09).

**Why:** 이 시스템은 문서가 들어올 때마다 즉시 처리하는 상시 ingestion 구조다. corpus 빈도
통계는 본질적으로 후행적이라 특정 connector(사이트)에서 처음 들어오는 문서 1~N개는 비교할
통계 자체가 없어 아무 필터도 못 받는다. "통계가 쌓이면 나중에 나아진다"는 상시 ingestion
파이프라인 입장에서는 문서마다 처리 결과가 달라지는 예측 불가능한 동작이지, 받아들일 수 있는
설계가 아니다. 탐지 로직을 Dagster asset으로 비동기 분리해도 cold-start 문제 자체는 없어지지
않는다 — 통계 계산 시점을 늦췄을 뿐 "처음 N개는 무방비"라는 구조적 한계는 그대로 남고, 새
connector(새 도메인)를 붙일 때마다 이 cold-start가 매번 반복된다.

**How to apply:** 앞으로 dedup이나 HTML 정제 관련 설계에서 "여러 문서를 모아서 통계를 낸 뒤
그 결과를 이후 문서에 적용" 하는 형태의 아이디어가 나오면, 이 상시 ingestion 구조(문서 1건씩
즉시 처리)와 맞는지부터 확인할 것. 맞지 않으면 비동기/배치로 우회하려 하지 말고 아예 다른
접근(예: connector 설정에 운영자가 직접 등록하는 결정적 문구/셀렉터 제외 목록 — 코퍼스 크기와
무관하게 첫 문서부터 동일하게 동작)을 검토해야 한다. 사이트 반복 boilerplate 자체는 여전히 열린
문제로 남아 있음 (`docs/internal/design/html-extraction.md` 6절 오픈 이슈).
