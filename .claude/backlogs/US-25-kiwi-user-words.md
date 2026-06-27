---
id: US-25
title: Kiwi 형태소 분석기 사용자 사전 파일 지원
status: todo
---

# US-25 — Kiwi 형태소 분석기 사용자 사전 파일 지원

## 배경

MinHash(Stage 2) dedup 파이프라인에서 Kiwi를 사용해 한국어 토큰을 추출한다.
도메인 특화 용어(임베딩, 청킹, Qdrant 등)는 기본 사전에 없어 토큰 품질이 낮을 수 있다.
사용자 사전 파일을 별도로 관리하고 런타임에 로드하여 분석 품질을 높인다.

## 목표

- TSV 형식의 사용자 사전 파일(`data/kiwi_user_words.tsv`)을 정의한다.
- 파일 경로는 `settings.yaml`의 `dedup.user_words_path`로 설정한다.
- Kiwi 인스턴스를 싱글턴으로 관리하며, 최초 호출 시 한 번만 파일을 로드한다.
- 파일이 없거나 경로가 비어 있으면 기본 사전만으로 동작한다(선택적 기능).

## 인수 조건

1. `data/kiwi_user_words.tsv`에 단어/품사/점수를 탭 구분으로 등록할 수 있다.
2. `#`으로 시작하는 줄은 주석으로 무시된다.
3. `settings.yaml`의 `dedup.user_words_path`를 빈 문자열로 설정하면 사용자 사전 없이 동작한다.
4. Kiwi 인스턴스는 프로세스 당 한 번만 생성된다(thread-safe).
5. 파일 경로가 설정되어 있으나 파일이 없으면 WARNING 로그를 남기고 계속 동작한다.
6. 기존 MinHash 토크나이저 단위 테스트가 통과한다.

## 범위 외

- 런타임 중 사전 핫 리로드
- UI/API를 통한 사전 편집
