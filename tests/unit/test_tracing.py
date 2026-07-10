"""Unit tests for src/tracing/ — span creation and traceparent extraction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rag_api.tracing.span import _extract_traceparent, tool_span

VALID_TRACEPARENT = "00-" + "a" * 32 + "-" + "b" * 16 + "-01"


@pytest.fixture()
def otel_provider(monkeypatch):
    """Isolated TracerProvider with in-memory exporter for each test.

    Uses monkeypatch to bypass OTel's one-time-set restriction on the global
    provider, so each test gets its own isolated exporter.
    """
    import opentelemetry.trace as otel_trace

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(otel_trace, "_TRACER_PROVIDER", provider)
    yield exporter


# ──────────────────────────────────────────────
# _extract_traceparent
# ──────────────────────────────────────────────

def test_extract_traceparent_none_ctx():
    assert _extract_traceparent(None) is None


def test_extract_traceparent_no_request_context():
    ctx = MagicMock(spec=[])  # no request_context attribute
    assert _extract_traceparent(ctx) is None


def test_extract_traceparent_meta_is_none():
    ctx = MagicMock()
    ctx.request_context.meta = None
    assert _extract_traceparent(ctx) is None


def test_extract_traceparent_meta_is_dict():
    ctx = MagicMock()
    ctx.request_context.meta = {"traceparent": VALID_TRACEPARENT}
    assert _extract_traceparent(ctx) == VALID_TRACEPARENT


def test_extract_traceparent_meta_is_dict_missing_key():
    ctx = MagicMock()
    ctx.request_context.meta = {"progressToken": 1}
    assert _extract_traceparent(ctx) is None


def test_extract_traceparent_meta_pydantic_model_extra():
    ctx = MagicMock()
    meta = MagicMock(spec=[])  # no model_extra, no traceparent
    ctx.request_context.meta = meta
    assert _extract_traceparent(ctx) is None


def test_extract_traceparent_meta_pydantic_model_with_extra():
    ctx = MagicMock()
    meta = MagicMock()
    meta.model_extra = {"traceparent": VALID_TRACEPARENT}
    ctx.request_context.meta = meta
    assert _extract_traceparent(ctx) == VALID_TRACEPARENT


# ──────────────────────────────────────────────
# tool_span
# ──────────────────────────────────────────────

def test_tool_span_creates_span_with_name(otel_provider):
    with tool_span("search", None):
        pass

    spans = otel_provider.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "mcp/tools/search"


def test_tool_span_sets_tool_name_attribute(otel_provider):
    with tool_span("list_knowledge_bases", None):
        pass

    spans = otel_provider.get_finished_spans()
    assert spans[0].attributes["mcp.tool.name"] == "list_knowledge_bases"


def test_tool_span_with_traceparent_creates_child_span(otel_provider):
    with tool_span("search", VALID_TRACEPARENT):
        pass

    spans = otel_provider.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    # Trace ID must match the one encoded in VALID_TRACEPARENT (all 'a's = 0xaa...aa)
    expected_trace_id = int("a" * 32, 16)
    assert span.context.trace_id == expected_trace_id


def test_tool_span_without_traceparent_creates_root_span(otel_provider):
    with tool_span("search", None):
        pass

    spans = otel_provider.get_finished_spans()
    assert len(spans) == 1
    # Root span has no parent
    assert spans[0].parent is None


def test_tool_span_with_traceparent_has_parent(otel_provider):
    with tool_span("search", VALID_TRACEPARENT):
        pass

    spans = otel_provider.get_finished_spans()
    assert spans[0].parent is not None


def test_tool_span_extra_attributes(otel_provider):
    with tool_span("search", None) as span:
        span.set_attribute("rag.query", "hello world")

    spans = otel_provider.get_finished_spans()
    assert spans[0].attributes["rag.query"] == "hello world"


def test_tool_span_safe_with_noop_provider(monkeypatch):
    # When no real provider is configured, tool_span must not raise.
    import opentelemetry.trace as otel_trace

    monkeypatch.setattr(otel_trace, "_TRACER_PROVIDER", None)
    with tool_span("search", None):
        pass
    with tool_span("search", VALID_TRACEPARENT):
        pass
