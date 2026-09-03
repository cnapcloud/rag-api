"""rag_api.hooks — registration-based callbacks fired just before a new document row is created.

Top-level module (a cross-cutting extension point, like exceptions.py): its emit() call
sites live in connectors/ and api/routers/, not in pipeline/. See
docs/internal/design/pipeline-hooks.md for the architecture. rag-api owns only the
registry, the event types, and HookAbort. Producers (connectors + upload routers) call
emit(); consumers (a vendoring app's startup) call register(). They never reference each
other. HookAbort is defined in rag_api.exceptions (all exception classes live there) and
re-exported here so `from rag_api.hooks import HookAbort` keeps working.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rag_api.exceptions import HookAbort

logger = logging.getLogger(__name__)

__all__ = ["BeforeDocCreate", "HookAbort", "emit", "register", "unregister"]

_registry: dict[type, list[Callable[[Any], None]]] = {}


@dataclass(frozen=True)
class BeforeDocCreate:
    """Fired right after get_doc_by_source() returns None (a new document is confirmed)
    and immediately before create_doc(). Not fired for re-sync, unchanged-skip, or
    fetch-failure error rows.
    """

    kb_id: str
    principal: Any = None
    source_type: str | None = None


def register(event_type: type, callback: Callable[[Any], None]) -> None:
    """Register a callback for an event type. Callbacks run in registration order.

    Registering the same (event_type, callback) pair twice is a no-op.
    """
    callbacks = _registry.setdefault(event_type, [])
    if callback in callbacks:
        logger.debug("Hook callback already registered: event=%s", event_type.__name__)
        return
    callbacks.append(callback)
    logger.debug("Hook callback registered: event=%s total=%d", event_type.__name__, len(callbacks))


def unregister(event_type: type, callback: Callable[[Any], None]) -> None:
    """Remove a previously registered callback. No-op if it was never registered."""
    callbacks = _registry.get(event_type)
    if not callbacks or callback not in callbacks:
        return
    callbacks.remove(callback)


def emit(event: Any) -> None:
    """Run every callback registered for type(event), in registration order.

    No-op when nothing is registered for the event type. Callback exceptions
    (HookAbort or otherwise) propagate out unchanged; subsequent callbacks do not run.
    """
    callbacks = _registry.get(type(event))
    if not callbacks:
        return
    for callback in list(callbacks):
        callback(event)


def _reset() -> None:
    """Test-only: drop all registrations."""
    _registry.clear()
