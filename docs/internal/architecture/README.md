# RAG API 아키텍처

> LlamaIndex + Dagster 기반 문서 인제스트 및 하이브리드 검색 파이프라인.

이 폴더는 관점별로 문서를 나눈다: [application.md](application.md)(애플리케이션 아키텍처, 정적 구조),
[technical.md](technical.md)(기술/인프라 아키텍처, 정적 인프라), [runtime.md](runtime.md)(런타임 뷰,
동적 처리 흐름).

---

## 1. 시스템 개요

### 개요도

```
        ┌─────────────┐          ┌──────────────┐
        │   FastAPI   │          │  Connector   │
        │ 업로드/삭제/  │          │  (web/conf/  │
        │ 재인덱싱     │          │   github)    │
        └──────┬──────┘          └──────┬───────┘
               │ S3 저장                 │ S3 스테이징
               │ + Redis 큐 적재          │ + Redis 큐 적재
               ↓                        ↓
              ┌────────────────────────┐
              │       Redis 큐          │
              └────────────┬───────────┘
                           │
               ┌───────────┴───────────┐
               ↓                       ↓
     event_queue_sensor         QueueWorker
        (Dagster)               (FastAPI 내장)
               └───────────┬───────────┘
                           ↓
              ┌────────────────────────┐
              │    인제스트 파이프라인      │
              │  validate → parse      │
              │  → dedup(중복 시 중단)   │
              │  → chunk → embed       │
              │  → upsert → meta       │
              └────────────┬───────────┘
                           │
           ┌───────────────┼───────────────┐
           ↓               ↓               ↓
          S3            Qdrant          Postgres
        (파일)        (벡터 DB)        (메타데이터)
```

### 핵심 설계 원칙

- **문서 단위 격리**: 문서 1개 = Dagster Run 1개. 문서별 독립 실패/재시도
- **다중 문서 병렬**: Sensor가 이벤트 N개 → `RunRequest` N개 반환 → Dagster가 `max_concurrent_runs` 내에서 병렬 실행
- **저장소 역할 분리**: Qdrant(벡터 청크), Postgres(KB/문서 메타데이터), Redis(인제스트·삭제 큐 전용)
- **이중 큐 소비 모드**: Dagster 환경은 `event_queue_sensor`, Dagster 없는 환경은 `QueueWorker`(FastAPI 내장 asyncio 워커)가 동일한 Redis 큐를 소비
- **순수 함수 Op**: 파이프라인 Op은 Dagster context 없이 동작하는 순수 함수. `runner.py`로 Dagster 없이도 직접 실행 가능

---

## 2. 문서 구성

| 문서 | 내용 |
|------|------|
| [application.md](application.md) | 레이어 구성, 컴포넌트 간 의존성, 예외 처리 전략, 로깅 전략, 설정 관리, 프로젝트 구조 |
| [technical.md](technical.md) | 데이터 흐름, 배포 토폴로지, 보안, 확장성/성능, 가용성/장애 복구, 헬스체크/모니터링 |
| [runtime.md](runtime.md) | Dagster 태스크 흐름, 검색 흐름, 이벤트 처리 경로, 커넥터 흐름, KB 삭제 흐름 (상세) |

design 문서 전체 목록(생성일순 + 설명)은 [design/README.md](../design/README.md) 참조.
아래는 자주 참조하는 핵심 문서만 발췌.

| 문서 | 내용 |
|------|------|
| [design/data-schema.md](../design/data-schema.md) | Qdrant payload, Postgres 테이블, Redis 큐 키 구조 |
| [design/doc-state-flow.md](../design/doc-state-flow.md) | 문서 상태 전이 및 API별 허용 조건 |
