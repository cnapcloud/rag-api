"""Unit tests for src/tracing/ — span creation and traceparent extraction."""

from __future__ import annotations

import asyncio
import io
from unittest.mock import MagicMock

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from rag_api.tracing.span import _extract_traceparent, rest_span, set_redacted_input, tool_span

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


# ──────────────────────────────────────────────
# rest_span
# ──────────────────────────────────────────────
#
# FastAPIInstrumentor creates exactly one HTTP server span per request and makes it the
# current span before the route handler runs. rest_span attaches attributes to that same
# span rather than creating a child — these tests simulate that by starting a span before
# calling the decorated handler, then asserting on that same (sole) finished span.

def _run_under_http_span(tracer_name: str, span_name: str, coro):
    tracer = otel_trace.get_tracer(tracer_name)
    with tracer.start_as_current_span(span_name):
        return asyncio.run(coro)


def test_rest_span_does_not_create_a_new_span(otel_provider):
    @rest_span
    async def list_kbs_endpoint():
        return {"knowledge_bases": []}

    _run_under_http_span("t1", "GET /api/kb", list_kbs_endpoint())

    spans = otel_provider.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "GET /api/kb"


def test_rest_span_sets_span_kind_chain(otel_provider):
    @rest_span
    async def list_kbs_endpoint():
        return {"knowledge_bases": []}

    _run_under_http_span("t2", "GET /api/kb", list_kbs_endpoint())

    attrs = otel_provider.get_finished_spans()[0].attributes
    assert attrs["openinference.span.kind"] == "CHAIN"


def test_rest_span_sets_input_and_output(otel_provider):
    @rest_span
    async def get_kb(kb_id: str):
        return {"kb_id": kb_id, "kb_name": "demo"}

    _run_under_http_span("t3", "GET /api/kb/{kb_id}", get_kb(kb_id="acme"))

    attrs = otel_provider.get_finished_spans()[0].attributes
    assert '"kb_id": "acme"' in attrs["input.value"]
    assert '"kb_name": "demo"' in attrs["output.value"]


def test_rest_span_skips_background_tasks_kwarg(otel_provider):
    from starlette.background import BackgroundTasks

    @rest_span
    async def trigger_sync(connector_id: str, background_tasks: BackgroundTasks):
        return {"connector_id": connector_id}

    _run_under_http_span(
        "t4",
        "POST /api/connectors/{connector_id}/sync",
        trigger_sync(connector_id="c1", background_tasks=BackgroundTasks()),
    )

    attrs = otel_provider.get_finished_spans()[0].attributes
    assert "background_tasks" not in attrs["input.value"]
    assert '"connector_id": "c1"' in attrs["input.value"]


def test_rest_span_skips_upload_file_kwarg(otel_provider):
    from fastapi import UploadFile

    @rest_span
    async def upload_doc(kb_id: str, file: UploadFile):
        return {"kb_id": kb_id}

    upload = UploadFile(io.BytesIO(b"data"), filename="a.txt")
    _run_under_http_span(
        "t5", "POST /api/kb/{kb_id}/docs/upload", upload_doc(kb_id="acme", file=upload)
    )

    attrs = otel_provider.get_finished_spans()[0].attributes
    assert "file" not in attrs["input.value"]
    assert '"kb_id": "acme"' in attrs["input.value"]


def test_rest_span_skips_upload_file_list_kwarg(otel_provider):
    from fastapi import UploadFile

    @rest_span
    async def upload_docs_batch(kb_id: str, files: list[UploadFile]):
        return {"kb_id": kb_id}

    uploads = [UploadFile(io.BytesIO(b"data"), filename="a.txt")]
    _run_under_http_span(
        "t6",
        "POST /api/kb/{kb_id}/docs/upload/batch",
        upload_docs_batch(kb_id="acme", files=uploads),
    )

    attrs = otel_provider.get_finished_spans()[0].attributes
    assert "files" not in attrs["input.value"]


def test_rest_span_skips_output_capture_for_streaming_response(otel_provider):
    from starlette.responses import StreamingResponse

    @rest_span
    async def download_doc():
        async def _iter():
            yield b"data"

        return StreamingResponse(_iter())

    _run_under_http_span("t7", "GET /api/kb/{kb_id}/docs/{doc_id}/download", download_doc())

    attrs = otel_provider.get_finished_spans()[0].attributes
    assert attrs["output.skipped"] == "streaming_response"
    assert "output.value" not in attrs


def test_rest_span_safe_with_noop_provider(monkeypatch):
    # No active span and no real provider — set_attribute on the NoOp span must not raise.
    monkeypatch.setattr(otel_trace, "_TRACER_PROVIDER", None)

    @rest_span
    async def get_kb(kb_id: str):
        return {"kb_id": kb_id}

    asyncio.run(get_kb(kb_id="acme"))


# ──────────────────────────────────────────────
# set_redacted_input
# ──────────────────────────────────────────────

def test_set_redacted_input_overrides_rest_span_input(otel_provider):
    @rest_span
    async def create_connector(body: dict):
        set_redacted_input({"body": {**body, "config": {"api_key": "***"}}})
        return {"connector_id": "c1"}

    _run_under_http_span(
        "t8",
        "POST /api/connectors",
        create_connector(body={"config": {"api_key": "super-secret"}}),
    )

    attrs = otel_provider.get_finished_spans()[0].attributes
    assert "super-secret" not in attrs["input.value"]
    assert '"api_key": "***"' in attrs["input.value"]
