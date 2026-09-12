"""Bounded-cardinality operational metrics with no portfolio labels."""

from __future__ import annotations

import math
from ipaddress import ip_address
from threading import Lock, Thread
from types import TracebackType
from wsgiref.simple_server import WSGIServer

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)


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
        self.queue_pending_items = Gauge(
            "queue_pending_items",
            "Durable events currently pending publication.",
            labelnames=("queue",),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.queue_oldest_pending_age_seconds = Gauge(
            "queue_oldest_pending_age_seconds",
            "Age in seconds of the oldest pending durable event.",
            labelnames=("queue",),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.queue_recoveries = Counter(
            "queue_recoveries_total",
            "Recovered durable queue claims by bounded reason.",
            labelnames=("queue", "reason"),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.queue_delivery_failures = Counter(
            "queue_delivery_failures_total",
            "Failed durable queue delivery attempts.",
            labelnames=("queue",),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.queue_delivery_attempts = Counter(
            "queue_delivery_attempts_total",
            "Durable queue delivery attempts by bounded outcome.",
            labelnames=("queue", "outcome"),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.queue_runs_without_deliverable_event = Gauge(
            "queue_runs_without_deliverable_event",
            "Queued runs found without a deliverable event in the latest dispatcher cycle.",
            labelnames=("queue",),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )

        self.database_query_duration = Histogram(
            "database_query_duration_seconds",
            "Cursor execution time; excludes result fetching and pool/connect time.",
            labelnames=("outcome",),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.phase2_queue_items = Gauge(
            "phase2_queue_items",
            "Current durable records, clipped at 1000; not cumulative attempt counts.",
            labelnames=("queue", "state"),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.phase2_queue_saturated = Gauge(
            "phase2_queue_saturated",
            "One means the reported queue count is a lower bound.",
            labelnames=("queue", "state"),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.phase2_queue_observed_at = Gauge(
            "phase2_queue_observed_at_seconds",
            "Time of the latest successful bounded queue snapshot.",
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.phase2_expiry_completed = Counter(
            "phase2_expiry_completed_total",
            "New completed capture expiry records, not purged rows or bytes.",
            labelnames=("family",),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )
        self.phase2_cycle_ready = Gauge(
            "phase2_cycle_ready",
            "One after the last successful family cycle; does not certify worker completion.",
            labelnames=("family",),
            namespace=namespace,
            subsystem=subsystem,
            registry=self.registry,
        )

    def observe_database_query(self, duration_seconds: float, failed: bool) -> None:
        if (
            type(failed) is not bool
            or isinstance(duration_seconds, bool)
            or not math.isfinite(duration_seconds)
            or duration_seconds < 0
        ):
            raise ValueError("A finite query duration and typed outcome are required.")
        self.database_query_duration.labels(outcome="failure" if failed else "success").observe(
            duration_seconds
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


class MetricsHttpServer:
    """Own a private-registry Prometheus listener and its complete lifecycle."""

    def __init__(self, *, server: WSGIServer, thread: Thread) -> None:
        self._server = server
        self._thread = thread
        self._close_lock = Lock()
        self._closed = False

    @classmethod
    def start(
        cls,
        *,
        metrics: OperationalMetrics,
        host: str,
        port: int,
    ) -> MetricsHttpServer:
        if not host or len(host) > 45:
            raise ValueError("metrics host must be a bounded IP address")
        try:
            normalized_host = str(ip_address(host))
        except ValueError as exc:
            raise ValueError("metrics host must be a bounded IP address") from exc
        if type(port) is not int or not 0 <= port <= 65_535:
            raise ValueError("metrics port is out of bounds")
        server, thread = start_http_server(
            port=port,
            addr=normalized_host,
            registry=metrics.registry,
        )
        return cls(server=server, thread=thread)

    @property
    def bound_port(self) -> int:
        return int(self._server.server_port)

    @property
    def is_running(self) -> bool:
        return self._thread.is_alive()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._server.shutdown()
            self._server.server_close()
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError("metrics HTTP server did not stop")
            self._closed = True

    def __enter__(self) -> MetricsHttpServer:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()
