"""Kiwi morphological analyzer singleton with optional user word dictionary."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

_kiwi = None
_lock = Lock()

_KIWI_AVAILABLE = False
try:
    import kiwipiepy as _kiwipiepy_check  # noqa: F401
    _KIWI_AVAILABLE = True
except ImportError:
    pass


def get_kiwi():
    """Return a shared Kiwi instance, initializing it once on first call.

    Loads user word dictionary from settings.dedup.minhash.user_words_path when set.
    Returns None when kiwipiepy is not installed.
    """
    if not _KIWI_AVAILABLE:
        return None

    global _kiwi
    if _kiwi is not None:
        return _kiwi

    with _lock:
        if _kiwi is not None:
            return _kiwi

        from kiwipiepy import Kiwi
        from rag_api.config.settings import get_settings

        kiwi = Kiwi()
        path_str = get_settings().dedup.minhash.user_words_path
        if path_str:
            _load_user_words(kiwi, Path(path_str))

        _kiwi = kiwi
        return _kiwi


def _load_user_words(kiwi, path: Path) -> None:
    if not path.is_absolute():
        path = Path.cwd() / path

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
                logger.warning("Skipping malformed line %d in %s: %r", lineno, path, line)
                continue
            word, tag = parts[0], parts[1]
            score = float(parts[2]) if len(parts) >= 3 else 10.0
            kiwi.add_user_word(word, tag, score=score)
            count += 1

    logger.info("Loaded %d user words from %s", count, path)
