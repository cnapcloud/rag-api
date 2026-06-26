"""Unit tests for pipeline/ops/dedup/simhash.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pipeline.ops.dedup.simhash import (
    compute_simhash,
    compute_title_hash,
    get_bands,
    hamming_distance,
    run_simhash_detection,
)
from pipeline.ops.dedup.types import DedupResult


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
# get_bands
# ──────────────────────────────────────────────

def test_get_bands_count():
    bands = get_bands(0xDEADBEEFCAFEBABE, num_bands=4, bits=64)
    assert len(bands) == 4


def test_get_bands_indices():
    bands = get_bands(0xDEADBEEFCAFEBABE, num_bands=4, bits=64)
    assert [i for i, _ in bands] == [0, 1, 2, 3]


# ──────────────────────────────────────────────
# run_simhash_detection — Redis mock
# ──────────────────────────────────────────────

def _make_cfg(hamming_threshold: int = 3):
    cfg = MagicMock()
    cfg.ngram = 3
    cfg.num_bands = 4
    cfg.simhash_bits = 64
    cfg.hamming_identical_threshold = hamming_threshold
    cfg.lock_ttl = 1
    cfg.lock_acquire_timeout = 1
    return cfg


def _make_redis(sunion_result=None, mget_result=None, setnx_returns=True):
    rc = MagicMock()
    rc.sunion.return_value = sunion_result or set()
    rc.mget.return_value = mget_result or []
    rc.set.return_value = setnx_returns
    rc.get.return_value = None
    rc.sadd.return_value = 1
    rc.delete.return_value = 1
    return rc


def test_run_simhash_detection_no_candidates():
    rc = _make_redis(sunion_result=set())
    result = run_simhash_detection("doc-1", "Title A", "body text content here", rc, _make_cfg())
    assert result.verdict == "proceed"
    assert result.needs_indexing is True
    rc.sadd.assert_called()


def test_run_simhash_detection_identical():
    body = "the quick brown fox " * 30
    simhash = compute_simhash(body, ngram=3, bits=64)
    title_hash = compute_title_hash("Same Title")

    rc = _make_redis(
        sunion_result={"existing-doc"},
        mget_result=[str(simhash)],
    )
    rc.get.return_value = title_hash

    result = run_simhash_detection("doc-new", "Same Title", body, rc, _make_cfg())
    assert result.verdict == "identical"
    assert result.needs_indexing is False
    assert result.duplicate_doc_id == "existing-doc"
    rc.sadd.assert_not_called()


def test_run_simhash_detection_title_changed():
    body = "the quick brown fox " * 30
    simhash = compute_simhash(body, ngram=3, bits=64)
    old_title_hash = compute_title_hash("Old Title")

    rc = _make_redis(
        sunion_result={"existing-doc"},
        mget_result=[str(simhash)],
    )
    rc.get.return_value = old_title_hash

    result = run_simhash_detection("doc-new", "New Title", body, rc, _make_cfg())
    assert result.verdict == "title_changed"
    assert result.needs_indexing is False
    assert result.duplicate_doc_id == "existing-doc"


def test_run_simhash_detection_excludes_self():
    body = "some document body content repeated " * 10
    simhash = compute_simhash(body, ngram=3, bits=64)

    rc = _make_redis(
        sunion_result={"doc-self"},
        mget_result=[str(simhash)],
    )

    result = run_simhash_detection("doc-self", "Title", body, rc, _make_cfg())
    assert result.verdict == "proceed"


def test_run_simhash_detection_lock_timeout_proceeds():
    rc = _make_redis()
    rc.set.return_value = False  # lock never acquired

    result = run_simhash_detection("doc-1", "Title", "body text here", rc, _make_cfg())
    assert result.verdict == "proceed"
