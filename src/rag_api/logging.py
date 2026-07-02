"""Shared logging setup for rag_api and any package that depends on it.

Design: a logger name's leading dotted segment (e.g. "rag_ent" in
"rag_ent.auth.jwks") identifies which package owns it. We attach one
StreamHandler to that top-level logger and set propagate=False, so a
third-party library that reconfigures the ROOT logger later (e.g.
qdrant-client/grpc, uvicorn) cannot silently change or duplicate our
app's log output. Each top-level segment is configured independently and
only once, either eagerly via setup_logging() (every name listed in
settings.logging.names) or lazily the first time get_logger() sees it --
so rag_api, rag_ent, or any future consumer package can share this one
module without writing a bespoke setup file of their own.
"""

from __future__ import annotations

import logging

_configured_namespaces: set[str] = set()


def _configure_namespace(top_level_name: str) -> None:
    """Attach handler/format/tracing filter to one top-level logger, once."""
    if top_level_name in _configured_namespaces:
        return

    from rag_api.config.settings import get_settings

    cfg = get_settings()
    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)

    logger = logging.getLogger(top_level_name)
    logger.setLevel(level)
    logger.propagate = False

    handler = logging.StreamHandler()
    if cfg.tracing.enabled:
        from rag_api.tracing.setup import OtelContextFilter

        fmt = "%(asctime)s %(levelname)s [%(trace_id)s:%(span_id)s] %(name)s: %(message)s"
        handler.addFilter(OtelContextFilter())
    else:
        fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)

    _configured_namespaces.add(top_level_name)


def setup_logging() -> None:
    """Eagerly configure every namespace listed in settings.logging.names."""
    from rag_api.config.settings import get_settings

    for top_level_name in get_settings().logging.names:
        _configure_namespace(top_level_name)


def get_logger(name: str) -> logging.Logger:
    """Return a logger for `name`, configuring its top-level namespace on first use.

    All application modules (in rag_api, rag_ent, or any other consumer
    package) should obtain their logger through this function instead of
    calling logging.getLogger() directly, so every logger shares one
    configuration seam. get_logger("rag_ent.auth.jwks") configures "rag_ent".
    """
    _configure_namespace(name.split(".", 1)[0])
    logger = logging.getLogger(name)
    logger.disabled = False
    return logger
