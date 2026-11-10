"""Minimal OpenTelemetry setup and safe span helper. No bid payload or credentials are recorded."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def setup_tracing(service_name: str) -> None:
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        return
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "jaeger:4317").removeprefix("http://").removeprefix("https://")
    configured = TracerProvider(resource=Resource.create({"service.name": service_name}))
    configured.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(configured)


def inject_context() -> dict[str, str]:
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


def extract_context(carrier: dict[str, str] | None) -> Context:
    return extract(carrier or {})


@contextmanager
def span(name: str, parent: Context | None = None, **attributes: str | int | float | bool) -> Iterator[None]:
    with trace.get_tracer("bid-compliance").start_as_current_span(name, context=parent) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        yield
