"""MCP tool span helper — creates child/root spans from traceparent."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.propagate import extract
from opentelemetry.trace import Span


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
    import json

    tool_name = fn.__name__

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
        return v

    def _to_json(v: Any) -> str:
        return json.dumps(_slim(v), ensure_ascii=False, default=str)

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
        yield span
