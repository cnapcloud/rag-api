"""MCP tool + REST handler span helpers — business span with input/output attributes."""

from __future__ import annotations

import functools
import inspect
import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.propagate import extract
from opentelemetry.trace import Span


def _is_unserializable_kwarg(v: Any) -> bool:
    """True for FastAPI kwarg types that shouldn't be JSON-serialized into a span attribute
    (BackgroundTasks, single or batch UploadFile)."""
    from fastapi import UploadFile
    from starlette.background import BackgroundTasks

    if isinstance(v, BackgroundTasks | UploadFile):
        return True
    return isinstance(v, list) and bool(v) and isinstance(v[0], UploadFile)


def _slim(v: Any, str_limit: int = 200, list_limit: int = 3) -> Any:
    if isinstance(v, str):
        return v[:str_limit] + "..." if len(v) > str_limit else v
    if isinstance(v, list):
        slimmed = [_slim(i, str_limit, list_limit) for i in v[:list_limit]]
        if len(v) > list_limit:
            return {"items": slimmed, "omitted": f"{len(v) - list_limit} items not shown"}
        return slimmed
    if isinstance(v, dict):
        return {k: _slim(val, str_limit, list_limit) for k, val in v.items()}
    if hasattr(v, "model_dump"):
        return _slim(v.model_dump(), str_limit, list_limit)
    return v


def _to_json(v: Any) -> str:
    return json.dumps(_slim(v), ensure_ascii=False, default=str)


def set_redacted_input(value: Any) -> None:
    """Overwrite input.value on the current span.

    For handlers wrapped in @rest_span that must redact sensitive fields (e.g. connector
    secrets) before export — span attributes aren't sent to the exporter until the span
    ends, so calling this after rest_span's initial (unredacted) write is safe: the last
    set_attribute call for a given key wins.
    """
    trace.get_current_span().set_attribute("input.value", _to_json(value))


def _extract_traceparent(ctx: Any) -> str | None:
    """Safely extract traceparent string from FastMCP Context._meta."""
    try:
        meta = ctx.request_context.meta  # type: ignore[union-attr]
    except AttributeError:
        return None
    if meta is None:
        return None
    if isinstance(meta, dict):
        return meta.get("traceparent")
    # Pydantic model with extra="allow" — extra fields accessible as attributes
    extras = getattr(meta, "model_extra", None) or {}
    return extras.get("traceparent") or getattr(meta, "traceparent", None)


def traced_tool(fn: Callable) -> Callable:
    """Decorator: wraps an MCP tool function in a tool_span.

    Extracts traceparent from the 'ctx' kwarg automatically.
    Sets input.value / output.value on the span so Langfuse shows them.
    Inside the decorated function use trace.get_current_span() to set extra attributes.
    """
    tool_name = fn.__name__

    def _input_json(kwargs: dict[str, Any]) -> str:
        return _to_json({k: v for k, v in kwargs.items() if k != "ctx"})

    @functools.wraps(fn)
    async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
        with tool_span(tool_name, _extract_traceparent(kwargs.get("ctx"))) as span:
            span.set_attribute("input.value", _input_json(kwargs))
            result = await fn(*args, **kwargs)
            span.set_attribute("output.value", _to_json(result))
            return result

    @functools.wraps(fn)
    def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        with tool_span(tool_name, _extract_traceparent(kwargs.get("ctx"))) as span:
            span.set_attribute("input.value", _input_json(kwargs))
            result = fn(*args, **kwargs)
            span.set_attribute("output.value", _to_json(result))
            return result

    return _async_wrapper if inspect.iscoroutinefunction(fn) else _sync_wrapper


@contextmanager
def tool_span(tool_name: str, traceparent: str | None) -> Generator[Span, None, None]:
    """Context manager that creates an OTel span for an MCP tool call.

    When traceparent is provided the span is a child of the remote trace.
    When None, the SDK auto-generates a new root trace ID.
    Safe to use even when tracing is disabled (NoOp provider).
    """
    tracer = trace.get_tracer("rag-api.mcp")
    ctx = extract({"traceparent": traceparent}) if traceparent else None
    with tracer.start_as_current_span(f"mcp/tools/{tool_name}", context=ctx) as span:
        span.set_attribute("mcp.tool.name", tool_name)
        span.set_attribute("openinference.span.kind", "TOOL")
        yield span


def rest_span(fn: Callable) -> Callable:
    """Decorator: attaches business attributes to the current REST HTTP span.

    Counterpart to traced_tool for REST routers. Unlike traced_tool/tool_span, this does
    NOT create a new child span — FastAPIInstrumentor already creates exactly one HTTP
    server span per request (named e.g. "POST /api/search"), and that route name already
    identifies the call, so a separate business span would just duplicate it. Instead,
    input.value/output.value/openinference.span.kind are set directly on
    trace.get_current_span(), i.e. that same HTTP span.

    Sets input.value from all handler kwargs (skipping non-serializable types like
    BackgroundTasks/UploadFile) and output.value from the return value. Handlers that return
    a streaming Response skip output capture. To redact sensitive fields (e.g. connector
    secrets) before export, call set_redacted_input(...) from inside the handler.
    """

    def _input_json(kwargs: dict[str, Any]) -> str:
        filtered = {k: v for k, v in kwargs.items() if not _is_unserializable_kwarg(v)}
        return _to_json(filtered)

    def _set_output(span: Span, result: Any) -> None:
        from starlette.responses import Response

        if isinstance(result, Response):
            span.set_attribute("output.skipped", "streaming_response")
            return
        span.set_attribute("output.value", _to_json(result))

    @functools.wraps(fn)
    async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
        span = trace.get_current_span()
        span.set_attribute("openinference.span.kind", "CHAIN")
        span.set_attribute("input.value", _input_json(kwargs))
        result = await fn(*args, **kwargs)
        _set_output(span, result)
        return result

    @functools.wraps(fn)
    def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        span = trace.get_current_span()
        span.set_attribute("openinference.span.kind", "CHAIN")
        span.set_attribute("input.value", _input_json(kwargs))
        result = fn(*args, **kwargs)
        _set_output(span, result)
        return result

    return _async_wrapper if inspect.iscoroutinefunction(fn) else _sync_wrapper
