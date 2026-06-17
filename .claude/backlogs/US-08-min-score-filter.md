# US-08: 검색 모드 분리 및 유사도 기반 필터

## 문제

현재 검색은 hybrid(dense+sparse RRF) 단일 경로만 존재한다.
RRF는 순위 기반 스코어(유사도 아님)라 "유사도 낮은 결과 제거"가 불가능하다.
유사도 기반 필터를 쓰려면 dense-only 경로가 필요하다.

## 요건

1. **검색 모드 2가지**
   - `hybrid`: 기존 dense+sparse, RRF 스코어 (변경 없음)
   - `similarity`: dense-only, 코사인 유사도 스코어 (0.0~1.0)

2. **설정 구조 재편** — 모드별 설정을 중첩 구조로 분리
   - `retrieval.hybrid.alpha`, `retrieval.hybrid.merge_strategy`
   - `retrieval.similarity.min_score` (기본값 0.0 = 필터 비활성)
   - 두 섹션 모두 settings.yaml에 공존; 비활성 섹션은 무시 (기존 `rerank.enabled=false` 패턴과 동일)
   - 기본 모드: `hybrid` — `mode` 키가 없으면 hybrid로 동작
   - 각 섹션 키가 없으면 해당 Pydantic 모델 기본값 사용 (`alpha=0.5`, `merge_strategy="rrf"`, `min_score=0.0`)

   ```yaml
   retrieval:
     mode: "hybrid"
     top_k: 10
     hybrid:
       alpha: 0.5
       merge_strategy: "rrf"
     similarity:
       min_score: 0.4
     rerank:
       ...
   ```

3. **min_score 필터** — similarity 모드에서만 동작
   - `score < min_score`인 결과 제거
   - 요청별 오버라이드 가능 (None이면 설정값 사용)

4. **mode 값 검증** — `Literal["hybrid", "similarity"]` 타입 적용
   - settings.yaml의 mode 값이 잘못되면 서버 기동 시 오류
   - API 요청의 mode 값이 잘못되면 422 자동 반환 (Pydantic 처리)

5. **rerank는 두 모드 모두 지원** — 기존 rerank 설정 구조 유지

6. **API SearchOptions 구조 변경**
   - `hybrid`, `similarity` 서브 옵션으로 분리
   - rerank는 공통 옵션으로 유지

## 인수 조건

- `mode=hybrid` (기본) → 기존 동작과 동일, 기존 테스트 전부 통과
- `mode=similarity`, `min_score=0.0` → 전체 결과 반환 (필터 없음)
- `mode=similarity`, `min_score=0.4` → 코사인 유사도 0.4 미만 결과 제거
- similarity 모드 + reranking on → min_score 필터 후 남은 결과를 rerank
- 모든 결과가 threshold 미만이면 빈 배열 반환 (오류 아님)
- `SearchMeta`에 실제 적용된 mode와 score_threshold 반환
