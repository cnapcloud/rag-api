---
plan: 25
title: Kiwi 사용자 사전 파일 지원
covers: US-25
status: todo
---

# Plan 25 — Kiwi 사용자 사전 파일 지원

## 개요

`data/kiwi_user_words.tsv` 파일을 런타임에 읽어 Kiwi에 등록하는 싱글턴 팩토리를 추가한다.
경로는 `settings.yaml`로 제어하여 하드코딩을 방지한다.

## 변경 파일 목록

| 파일 | 변경 종류 | 내용 |
|------|-----------|------|
| `src/config/settings.py` | 수정 | `DedupSettings.user_words_path: str = ""` 필드 추가 |
| `settings.yaml` | 수정 | `dedup.user_words_path: "data/kiwi_user_words.tsv"` 추가 |
| `data/kiwi_user_words.tsv` | 신규 | 도메인 용어 사전 (주석 포함) |
| `src/pipeline/ops/dedup/tokenizer.py` | 신규 | `get_kiwi()` 싱글턴 + `_load_user_words()` |
| `src/pipeline/ops/dedup/minhash.py` | 수정 | `tokenize()` 내부에서 `get_kiwi()` 호출로 교체 |
| `tests/unit/test_dedup_minhash.py` | 수정 | tokenizer 싱글턴 초기화 격리 픽스처 추가 |

## 구현 단계

### 1. `DedupSettings` 필드 추가

```python
# src/config/settings.py — DedupSettings
user_words_path: str = ""
```

### 2. `settings.yaml` 경로 설정

```yaml
dedup:
  user_words_path: "data/kiwi_user_words.tsv"
```

### 3. 사전 파일 생성 (`data/kiwi_user_words.tsv`)

```
# 형식: word<TAB>tag<TAB>score
# 태그: NNG=일반명사, NNP=고유명사, SL=외국어
임베딩	NNG	10.0
청킹	NNG	10.0
리랭킹	NNG	10.0
벡터스토어	NNG	10.0
Qdrant	SL	10.0
MinIO	SL	10.0
RAG	SL	10.0
```

### 4. `tokenizer.py` 싱글턴 팩토리

```python
# src/pipeline/ops/dedup/tokenizer.py
_kiwi = None
_lock = Lock()


def get_kiwi():
    global _kiwi
    if _kiwi is not None:
        return _kiwi
    with _lock:
        if _kiwi is not None:
            return _kiwi
        from kiwipiepy import Kiwi
        from rag_api.config.settings import get_settings
        kiwi = Kiwi()
        path_str = get_settings().dedup.user_words_path
        if path_str:
            _load_user_words(kiwi, Path(path_str))
        _kiwi = kiwi
        return _kiwi


def _load_user_words(kiwi, path: Path) -> None:
    if not path.is_absolute():
        root = Path(__file__).parents[4]
        path = root / path
    if not path.exists():
        logger.warning("Kiwi user words file not found: %s", path)
        return
    count = 0
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                logger.warning("Skipping malformed line %d: %r", lineno, line)
                continue
            word, tag = parts[0], parts[1]
            score = float(parts[2]) if len(parts) >= 3 else 10.0
            kiwi.add_user_word(word, tag, score=score)
            count += 1
    logger.info("Loaded %d user words from %s", count, path)
```

### 5. `minhash.py` tokenize 교체

기존 `minhash.py`의 Kiwi 직접 생성 코드를 `get_kiwi()` 호출로 교체.

### 6. 테스트 격리

싱글턴 `_kiwi`가 테스트 간 오염되지 않도록 픽스처로 초기화:

```python
@pytest.fixture(autouse=True)
def reset_kiwi_singleton():
    from rag_api import pipeline as tok
    tok._kiwi = None
    yield
    tok._kiwi = None
```

`user_words_path = ""` 설정으로 파일 로드 없이 동작 검증.

## 의존성 / 전제 조건

- `kiwipiepy` 패키지가 `pyproject.toml`에 이미 있어야 함 (US-24에서 추가 여부 확인 필요)
- `data/` 디렉토리가 project root에 존재해야 함

## 완료 기준

- `make test` (단위 테스트 전체) 통과
- `data/kiwi_user_words.tsv` 존재
- `settings.yaml`에 `user_words_path` 설정 포함
