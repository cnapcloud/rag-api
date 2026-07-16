"""Unit tests for pipeline/step/dedup/minhash.py and tokenizer.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from rag_api import pipeline as _tok_module
from rag_api.pipeline.step.dedup.minhash import (
    compute_jaccard,
    compute_minhash,
    split_bands,
)


@pytest.fixture(autouse=True)
def reset_kiwi_singleton():
    """Reset the Kiwi singleton between tests to prevent cross-test pollution."""
    _tok_module._kiwi = None
    yield
    _tok_module._kiwi = None


# ──────────────────────────────────────────────
# compute_minhash
# ──────────────────────────────────────────────

def test_minhash_signature_length():
    sig = compute_minhash(["word1", "word2", "word3"])
    assert len(sig) == 128


def test_minhash_empty_tokens_returns_128():
    sig = compute_minhash([])
    assert len(sig) == 128


def test_minhash_deterministic():
    tokens = ["the", "quick", "brown", "fox"]
    assert compute_minhash(tokens) == compute_minhash(tokens)


def test_minhash_identical_token_sets_equal():
    tokens = ["alpha", "beta", "gamma"]
    assert compute_minhash(tokens) == compute_minhash(tokens[::-1])


# ──────────────────────────────────────────────
# split_bands
# ──────────────────────────────────────────────

def test_split_bands_count():
    sig = list(range(128))
    bands = split_bands(sig, num_bands=16)
    assert len(bands) == 16


def test_split_bands_deterministic():
    sig = list(range(128))
    assert split_bands(sig, 16) == split_bands(sig, 16)


def test_split_bands_identical_sigs_equal():
    sig_a = compute_minhash(["word"] * 10)
    sig_b = compute_minhash(["word"] * 10)
    assert split_bands(sig_a, 16) == split_bands(sig_b, 16)


# ──────────────────────────────────────────────
# compute_jaccard
# ──────────────────────────────────────────────

def test_compute_jaccard_identical():
    sig = [1, 2, 3, 4, 5]
    assert compute_jaccard(sig, sig) == 1.0


def test_compute_jaccard_disjoint():
    sig_a = [1, 2, 3]
    sig_b = [4, 5, 6]
    assert compute_jaccard(sig_a, sig_b) == 0.0


def test_compute_jaccard_partial():
    sig_a = [1, 2, 3, 4]
    sig_b = [1, 2, 9, 9]
    assert compute_jaccard(sig_a, sig_b) == 0.5


def test_compute_jaccard_empty():
    assert compute_jaccard([], []) == 0.0


def test_minhash_identical_texts_jaccard_one():
    tokens = ["apple", "banana", "cherry", "date", "elderberry"] * 10
    sig = compute_minhash(tokens)
    assert compute_jaccard(sig, sig) == 1.0


def test_minhash_unrelated_texts_low_jaccard():
    tokens_a = [f"aardvark_{i}" for i in range(50)]
    tokens_b = [f"zucchini_{i}" for i in range(50)]
    sig_a = compute_minhash(tokens_a)
    sig_b = compute_minhash(tokens_b)
    assert compute_jaccard(sig_a, sig_b) < 0.1


# ──────────────────────────────────────────────
# run_minhash_detection
# ──────────────────────────────────────────────

def _make_cfg(jaccard_threshold=0.65, title_fuzzy_threshold=0.85, title_only_min_jaccard_floor=0.25):
    cfg = MagicMock()
    cfg.jaccard_threshold = jaccard_threshold
    cfg.title_fuzzy_threshold = title_fuzzy_threshold
    cfg.title_only_min_jaccard_floor = title_only_min_jaccard_floor
    return cfg


_PG_FIND_BODY = "rag_api.infra.postgres.find_minhash_candidates"
_PG_FIND_TITLE = "rag_api.infra.postgres.find_title_candidates"
_PG_SAVE = "rag_api.infra.postgres.save_minhash_bands"
_PG_GET = "rag_api.infra.postgres.get_minhash_signature"


def test_run_minhash_detection_no_candidates_returns_proceed():
    from rag_api.pipeline.step.dedup.minhash import run_minhash_detection

    with patch(_PG_FIND_BODY, return_value=set()), \
         patch(_PG_FIND_TITLE, return_value={}), \
         patch(_PG_SAVE):
        result = run_minhash_detection("doc-1", "some text content here", "Title A", _make_cfg())

    assert result.body_match == "none"
    assert result.needs_indexing is True


def test_run_minhash_detection_saves_signature():
    from rag_api.pipeline.step.dedup.minhash import run_minhash_detection

    with patch(_PG_FIND_BODY, return_value=set()), \
         patch(_PG_FIND_TITLE, return_value={}), \
         patch(_PG_SAVE) as mock_save:
        run_minhash_detection("doc-1", "text", "Title", _make_cfg())

    mock_save.assert_called_once()
    saved_sig = mock_save.call_args[0][1]
    assert len(saved_sig) == 128


def test_run_minhash_detection_similar_by_jaccard():
    from rag_api.pipeline.step.dedup.minhash import compute_minhash, run_minhash_detection

    tokens = ["shared_word"] * 60 + [f"unique_a_{i}" for i in range(5)]
    sig = compute_minhash(tokens)

    with patch(_PG_FIND_BODY, return_value={"doc-c"}), \
         patch(_PG_FIND_TITLE, return_value={}), \
         patch(_PG_SAVE), \
         patch(_PG_GET, return_value=sig):  # identical sig → Jaccard = 1.0
        result = run_minhash_detection("doc-1", " ".join(tokens), "Title", _make_cfg())

    assert result.body_match == "similar"
    assert result.needs_indexing is False
    assert result.duplicate_doc_id == "doc-c"


def test_run_minhash_detection_similar_excludes_self():
    from rag_api.pipeline.step.dedup.minhash import compute_minhash, run_minhash_detection

    tokens = ["word"] * 50
    sig = compute_minhash(tokens)

    with patch(_PG_FIND_BODY, return_value={"doc-self"}), \
         patch(_PG_FIND_TITLE, return_value={}), \
         patch(_PG_SAVE), \
         patch(_PG_GET, return_value=sig):
        result = run_minhash_detection("doc-self", " ".join(tokens), "Title", _make_cfg())

    assert result.body_match == "none"


def test_run_minhash_detection_similar_by_title_above_floor():
    from rag_api.pipeline.step.dedup.minhash import compute_minhash, run_minhash_detection

    # Make sig_a and sig_c share ~30% of values (above floor=0.25, below threshold=0.65)
    shared = [f"token_{i}" for i in range(30)]
    only_a = [f"aaa_{i}" for i in range(70)]
    only_c = [f"zzz_{i}" for i in range(70)]

    sig_a = compute_minhash(shared + only_a)
    sig_c = compute_minhash(shared + only_c)

    with patch(_PG_FIND_BODY, return_value=set()), \
         patch(_PG_FIND_TITLE, return_value={"doc-c": 0.92}), \
         patch(_PG_SAVE), \
         patch(_PG_GET, return_value=sig_c):
        cfg = _make_cfg(jaccard_threshold=0.65, title_fuzzy_threshold=0.85,
                        title_only_min_jaccard_floor=0.15)
        result = run_minhash_detection("doc-1", " ".join(shared + only_a), "Same Title", cfg)

    j = compute_jaccard(sig_a, sig_c)
    if j >= cfg.title_only_min_jaccard_floor:
        assert result.body_match == "similar"
    else:
        assert result.body_match == "none"


def test_run_minhash_detection_proceed_when_jaccard_below_floor():
    from rag_api.pipeline.step.dedup.minhash import compute_minhash, run_minhash_detection

    # Completely different tokens → Jaccard ≈ 0 → below floor
    tokens_a = [f"apple_{i}" for i in range(50)]
    tokens_c = [f"zebra_{i}" for i in range(50)]
    sig_c = compute_minhash(tokens_c)

    with patch(_PG_FIND_BODY, return_value=set()), \
         patch(_PG_FIND_TITLE, return_value={"doc-c": 0.92}), \
         patch(_PG_SAVE), \
         patch(_PG_GET, return_value=sig_c):
        cfg = _make_cfg(jaccard_threshold=0.65, title_fuzzy_threshold=0.85,
                        title_only_min_jaccard_floor=0.25)
        result = run_minhash_detection("doc-1", " ".join(tokens_a), "Same Title", cfg)

    # Jaccard(apple_*, zebra_*) ≈ 0 < floor=0.25 → proceed despite title match
    assert result.body_match == "none"
    assert result.needs_indexing is True


def test_run_minhash_detection_candidate_without_signature_is_skipped():
    from rag_api.pipeline.step.dedup.minhash import run_minhash_detection

    with patch(_PG_FIND_BODY, return_value={"doc-c"}), \
         patch(_PG_FIND_TITLE, return_value={}), \
         patch(_PG_SAVE), \
         patch(_PG_GET, return_value=None):  # no stored signature
        result = run_minhash_detection("doc-1", "some text", "Title", _make_cfg())

    assert result.body_match == "none"


# ──────────────────────────────────────────────
# tokenizer.py — get_kiwi()
# ──────────────────────────────────────────────

def test_get_kiwi_returns_none_when_unavailable():
    from rag_api.pipeline.step.dedup import tokenizer as tok

    with patch.object(tok, "_KIWI_AVAILABLE", False):
        result = tok.get_kiwi()
    assert result is None


def test_get_kiwi_returns_instance_when_available():
    import sys

    from rag_api.pipeline.step.dedup import tokenizer as tok

    mock_kiwi_instance = MagicMock()
    mock_kiwi_module = MagicMock()
    mock_kiwi_module.Kiwi = MagicMock(return_value=mock_kiwi_instance)

    with patch.object(tok, "_KIWI_AVAILABLE", True), \
         patch.object(tok, "_kiwi", None), \
         patch.dict(sys.modules, {"kiwipiepy": mock_kiwi_module}), \
         patch("rag_api.config.settings.get_settings") as ms:
        ms.return_value.dedup.minhash.user_words_path = ""
        result = tok.get_kiwi()

    assert result is mock_kiwi_instance


def test_get_kiwi_missing_user_words_file_logs_warning(tmp_path, caplog):
    import logging
    import sys

    from rag_api.pipeline.step.dedup import tokenizer as tok

    mock_kiwi_instance = MagicMock()
    mock_kiwi_module = MagicMock()
    mock_kiwi_module.Kiwi = MagicMock(return_value=mock_kiwi_instance)

    with patch.object(tok, "_KIWI_AVAILABLE", True), \
         patch.object(tok, "_kiwi", None), \
         patch.dict(sys.modules, {"kiwipiepy": mock_kiwi_module}), \
         patch("rag_api.config.settings.get_settings") as ms, \
         caplog.at_level(logging.WARNING, logger="rag_api.pipeline.step.dedup.tokenizer"):
        ms.return_value.dedup.minhash.user_words_path = str(tmp_path / "nonexistent.tsv")
        tok.get_kiwi()

    assert any("not found" in r.message for r in caplog.records)
    mock_kiwi_instance.add_user_word.assert_not_called()


def test_load_user_words_registers_entries(tmp_path):
    from rag_api.pipeline.step.dedup.tokenizer import _load_user_words

    tsv = tmp_path / "words.tsv"
    tsv.write_text("# comment\n임베딩\tNNG\t10.0\nRAG\tSL\t8.0\n\n", encoding="utf-8")

    mock_kiwi = MagicMock()
    _load_user_words(mock_kiwi, tsv)

    assert mock_kiwi.add_user_word.call_count == 2
    mock_kiwi.add_user_word.assert_any_call("임베딩", "NNG", score=10.0)
    mock_kiwi.add_user_word.assert_any_call("RAG", "SL", score=8.0)


def test_load_user_words_skips_malformed_lines(tmp_path, caplog):
    import logging

    from rag_api.pipeline.step.dedup.tokenizer import _load_user_words

    tsv = tmp_path / "words.tsv"
    tsv.write_text("good\tNNG\t5.0\nno_tab_here\n", encoding="utf-8")

    mock_kiwi = MagicMock()
    with caplog.at_level(logging.WARNING, logger="rag_api.pipeline.step.dedup.tokenizer"):
        _load_user_words(mock_kiwi, tsv)

    assert mock_kiwi.add_user_word.call_count == 1
    assert any("malformed" in r.message for r in caplog.records)
