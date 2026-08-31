"""Bounded-cardinality operational metrics with no portfolio labels."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


class OperationalMetrics:
    def __init__(self, *, service: str) -> None:
        if not service or len(service) > 80:
            raise ValueError("service name must be non-empty and bounded")
        self.registry = CollectorRegistry(auto_describe=True)
        namespace = "t212pi"
        subsystem = service.replace("-", "_")
        self.requests = Counter(
            "requests_total",
            "Completed bounded application operations.",
            labelnames=("operation", "outcome"),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.duration = Histogram(
            "operation_duration_seconds",
            "Bounded application operation duration.",
            labelnames=("operation",),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.failures = Counter(
            "failures_total",
            "Sanitized operational failures by stable category.",
            labelnames=("category",),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.readiness = Gauge(
            "ready",
            "One when required service dependencies are ready.",
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)
