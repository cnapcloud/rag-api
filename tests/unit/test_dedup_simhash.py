"""Unit tests for pipeline/ops/dedup/simhash.py."""

from __future__ import annotations

from unittest.mock import patch

from rag_api.pipeline.ops.dedup.simhash import (
    compute_simhash,
    compute_title_hash,
    get_bands,
    hamming_distance,
    i64_to_u64,
    run_simhash_detection,
    u64_to_i64,
)

# ──────────────────────────────────────────────
# compute_title_hash
# ──────────────────────────────────────────────

def test_title_hash_deterministic():
    assert compute_title_hash("hello") == compute_title_hash("hello")


def test_title_hash_different_titles():
    assert compute_title_hash("hello") != compute_title_hash("world")


def test_title_hash_strips_whitespace():
    assert compute_title_hash("  hello  ") == compute_title_hash("hello")


# ──────────────────────────────────────────────
# compute_simhash
# ──────────────────────────────────────────────

def test_simhash_identical_text():
    text = "the quick brown fox jumps over the lazy dog"
    assert compute_simhash(text) == compute_simhash(text)


def test_simhash_different_texts_differ():
    a = compute_simhash("completely different document content here")
    b = compute_simhash("another entirely unrelated text with no overlap at all")
    assert a != b


def test_simhash_near_duplicate_low_hamming():
    base = "the quick brown fox jumps over the lazy dog " * 20
    modified = base.replace("quick", "fast", 1)
    dist = hamming_distance(compute_simhash(base), compute_simhash(modified))
    assert dist <= 10


def test_simhash_returns_64bit():
    h = compute_simhash("test text", bits=64)
    assert 0 <= h < (1 << 64)


def test_simhash_ngram3_korean():
    text = "안녕하세요 반갑습니다 오늘 날씨가 맑습니다"
    h = compute_simhash(text, ngram=3)
    assert isinstance(h, int)
    assert h != 0


# ──────────────────────────────────────────────
# hamming_distance
# ──────────────────────────────────────────────

def test_hamming_identical():
    assert hamming_distance(0b1010, 0b1010) == 0


def test_hamming_one_bit():
    assert hamming_distance(0b1010, 0b1011) == 1


def test_hamming_all_bits():
    assert hamming_distance(0, 0xFFFF_FFFF_FFFF_FFFF) == 64


# ──────────────────────────────────────────────
# u64_to_i64 / i64_to_u64
# ──────────────────────────────────────────────

def test_u64_i64_roundtrip_positive():
    v = (1 << 63) - 1
    assert i64_to_u64(u64_to_i64(v)) == v


def test_u64_i64_roundtrip_high_bit():
    v = (1 << 63)
    assert i64_to_u64(u64_to_i64(v)) == v


def test_u64_i64_roundtrip_max():
    v = (1 << 64) - 1
    assert i64_to_u64(u64_to_i64(v)) == v


# ──────────────────────────────────────────────
# get_bands
# ──────────────────────────────────────────────

def test_get_bands_count():
    bands = get_bands(0xDEADBEEFCAFEBABE, num_bands=4, bits=64)
    assert len(bands) == 4


def test_get_bands_indices():
    bands = get_bands(0xDEADBEEFCAFEBABE, num_bands=4, bits=64)
    assert [i for i, _ in bands] == [0, 1, 2, 3]


# ──────────────────────────────────────────────
# run_simhash_detection — Postgres mock
# ──────────────────────────────────────────────

_PG_FIND = "rag_api.infra.postgres.find_simhash_candidates"
_PG_FP = "rag_api.infra.postgres.get_docs_fingerprints"
_PG_SAVE = "rag_api.infra.postgres.save_simhash_bands"
_PG_UPDATE = "rag_api.infra.postgres.update_doc_fields"


def _make_cfg(hamming_identical_threshold: int = 3, hamming_similar_threshold: int = 10):
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.ngram = 3
    cfg.num_bands = 4
    cfg.simhash_bits = 64
    cfg.hamming_identical_threshold = hamming_identical_threshold
    cfg.hamming_similar_threshold = hamming_similar_threshold
    return cfg


def test_run_simhash_detection_no_candidates():
    with patch(_PG_FIND, return_value=set()), \
         patch(_PG_FP, return_value={}), \
         patch(_PG_SAVE) as mock_save, \
         patch(_PG_UPDATE):
        result = run_simhash_detection("doc-1", "Title A", "body text content here", _make_cfg())

    assert result.body_match == "none"
    assert result.needs_indexing is True
    mock_save.assert_called_once()


def test_run_simhash_detection_identical():
    body = "the quick brown fox " * 30
    simhash = compute_simhash(body, ngram=3, bits=64)
    title_hash = compute_title_hash("Same Title")

    with patch(_PG_FIND, return_value={"existing-doc"}), \
         patch(_PG_FP, return_value={"existing-doc": {
             "content_simhash": u64_to_i64(simhash),
             "title_hash": title_hash,
         }}), \
         patch(_PG_SAVE) as mock_save, \
         patch(_PG_UPDATE):
        result = run_simhash_detection("doc-new", "Same Title", body, _make_cfg())

    assert result.body_match == "identical_level"
    assert result.title_match == "same"
    assert result.needs_indexing is False
    assert result.duplicate_doc_id == "existing-doc"
    mock_save.assert_not_called()


def test_run_simhash_detection_title_changed():
    body = "the quick brown fox " * 30
    simhash = compute_simhash(body, ngram=3, bits=64)
    old_title_hash = compute_title_hash("Old Title")

    with patch(_PG_FIND, return_value={"existing-doc"}), \
         patch(_PG_FP, return_value={"existing-doc": {
             "content_simhash": u64_to_i64(simhash),
             "title_hash": old_title_hash,
         }}), \
         patch(_PG_SAVE), \
         patch(_PG_UPDATE):
        result = run_simhash_detection("doc-new", "New Title", body, _make_cfg())

    assert result.body_match == "identical_level"
    assert result.title_match == "changed"
    assert result.needs_indexing is False
    assert result.duplicate_doc_id == "existing-doc"


def test_run_simhash_detection_excludes_self():
    body = "some document body content repeated " * 10

    with patch(_PG_FIND, return_value={"doc-self"}), \
         patch(_PG_FP, return_value={}), \
         patch(_PG_SAVE), \
         patch(_PG_UPDATE):
        result = run_simhash_detection("doc-self", "Title", body, _make_cfg())

    assert result.body_match == "none"


def test_run_simhash_detection_similar_hamming_between_thresholds():
    """Candidate found with hamming in (identical, similar] → similar verdict."""
    body = "the quick brown fox " * 30
    simhash = compute_simhash(body, ngram=3, bits=64)

    modified_simhash = simhash ^ ((1 << 5) - 1)
    dist = hamming_distance(simhash, modified_simhash)
    assert 3 < dist <= 10, f"Expected dist in (3,10], got {dist}"

    with patch(_PG_FIND, return_value={"existing-doc"}), \
         patch(_PG_FP, return_value={"existing-doc": {
             "content_simhash": u64_to_i64(modified_simhash),
             "title_hash": compute_title_hash("Any Title"),
         }}), \
         patch(_PG_SAVE), \
         patch(_PG_UPDATE):
        result = run_simhash_detection(
            "doc-new", "Any Title", body,
            _make_cfg(hamming_identical_threshold=3, hamming_similar_threshold=10),
        )

    assert result.body_match == "similar"
    assert result.needs_indexing is False
    assert result.duplicate_doc_id == "existing-doc"


def test_run_simhash_detection_beyond_similar_threshold_returns_proceed():
    """Candidate with Hamming > similar threshold → proceed (to stage 2)."""
    body = "the quick brown fox " * 30
    simhash = compute_simhash(body, ngram=3, bits=64)

    modified_simhash = simhash ^ ((1 << 15) - 1)
    dist = hamming_distance(simhash, modified_simhash)
    assert dist > 10, f"Expected dist > 10, got {dist}"

    with patch(_PG_FIND, return_value={"existing-doc"}), \
         patch(_PG_FP, return_value={"existing-doc": {
             "content_simhash": u64_to_i64(modified_simhash),
             "title_hash": compute_title_hash("Title"),
         }}), \
         patch(_PG_SAVE) as mock_save, \
         patch(_PG_UPDATE):
        result = run_simhash_detection(
            "doc-new", "Title", body,
            _make_cfg(hamming_identical_threshold=3, hamming_similar_threshold=10),
        )

    assert result.body_match == "none"
    assert result.needs_indexing is True
    mock_save.assert_called_once()


def test_run_simhash_detection_candidate_missing_fingerprint_skipped():
    """Candidate with no stored content_simhash is skipped."""
    body = "the quick brown fox " * 30

    with patch(_PG_FIND, return_value={"existing-doc"}), \
         patch(_PG_FP, return_value={"existing-doc": {
             "content_simhash": None,
             "title_hash": None,
         }}), \
         patch(_PG_SAVE), \
         patch(_PG_UPDATE):
        result = run_simhash_detection("doc-new", "Title", body, _make_cfg())

    assert result.body_match == "none"
