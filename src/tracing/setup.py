"""OpenTelemetry TracerProvider initialization — Langfuse OTLP exporter."""

from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)


class OtelContextFilter(logging.Filter):
    """Injects current OTel trace_id and span_id into every LogRecord.

    Returns "-" for both fields when no span is active (tracing disabled or outside a span).
    Add to handlers so all propagated records are covered.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from opentelemetry import trace

        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
        else:
            record.trace_id = "-"
            record.span_id = "-"
        return True


def init_tracing() -> None:
    from config.settings import get_settings

    cfg = get_settings().tracing
    if not cfg.enabled:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    credentials = base64.b64encode(
        f"{cfg.langfuse_public_key}:{cfg.langfuse_secret_key}".encode()
    ).decode()
    exporter = OTLPSpanExporter(
        endpoint=f"{cfg.langfuse_baseurl}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {credentials}"},
    )
    resource = Resource.create({"service.name": cfg.service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    set_global_textmap(TraceContextTextMapPropagator())
    logger.info(
        "Tracing initialized OK: service=%s endpoint=%s/api/public/otel/v1/traces",
        cfg.service_name,
        cfg.langfuse_baseurl,
    )


def shutdown_tracing() -> None:
    from config.settings import get_settings

    if not get_settings().tracing.enabled:
        return

    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
    if hasattr(provider, "shutdown"):
        provider.shutdown()
    logger.info("Tracing shut down")
