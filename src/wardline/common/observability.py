"""Tracing + metrics (report's security/ops plane).

Console span exporter by default (`OTEL_EXPORTER_OTLP_ENDPOINT` unset) — no
extra service required to see traces during local dev. Set that setting to
route through the bundled `otel-collector` compose service (or any real
OTLP endpoint) without a code change. `/metrics` is a standard unauthenticated
Prometheus scrape target — that's normal for this kind of endpoint (protect
it at the network perimeter, not in application code, the same way most
Prometheus exporters work).
"""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_fastapi_instrumentator import Instrumentator

from wardline.common.config import Settings


def configure_observability(app: FastAPI, settings: Settings) -> None:
    resource = Resource.create({"service.name": settings.app_name, "service.version": "0.1.0"})
    provider = TracerProvider(resource=resource)

    exporter = (
        OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
        if settings.otel_exporter_otlp_endpoint
        else ConsoleSpanExporter()
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
