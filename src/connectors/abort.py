"""In-process abort registry for connector sync operations.

Abort requests are held in memory — they are cleared when the sync finishes
or when the process restarts. A restarted process will also kill the
BackgroundTask thread, so this is sufficient.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_abort_set: set[str] = set()


def request_abort(connector_id: str) -> None:
    with _lock:
        _abort_set.add(connector_id)


def clear_abort(connector_id: str) -> None:
    with _lock:
        _abort_set.discard(connector_id)


def is_abort_requested(connector_id: str) -> bool:
    with _lock:
        return connector_id in _abort_set
