from __future__ import annotations

import io
import json
import logging
from contextlib import redirect_stderr, redirect_stdout
from http.client import HTTPConnection

from trading212_observability import (
    MetricsHttpServer,
    OperationalMetrics,
    configure_logging,
    logger,
)

CANARY = "OBSERVABILITY-CANARY-SECRET"


def test_structured_logs_redact_sensitive_keys_headers_and_canaries() -> None:
    configure_logging(service="test", secret_canaries=(CANARY,))
    output = io.StringIO()
    with redirect_stdout(output):
        logger("test").info(
            "provider_read_failed",
            api_key="private-key",
            detail=f"Bearer bearer-value {CANARY}",
            operation="portfolio_summary",
        )
    rendered = output.getvalue()
    assert "provider_read_failed" in rendered
    assert "portfolio_summary" in rendered
    assert "private-key" not in rendered
    assert "bearer-value" not in rendered
    assert CANARY not in rendered
    assert rendered.count("[REDACTED]") >= 2


def test_metrics_have_only_bounded_operational_labels() -> None:
    metrics = OperationalMetrics(service="api")
    metrics.requests.labels(operation="summary", outcome="success").inc()
    metrics.failures.labels(category="contract").inc()
    metrics.readiness.set(1)
    rendered = metrics.render().decode()
    assert 'operation="summary"' in rendered
    assert 'category="contract"' in rendered
    assert "account_id" not in rendered
    assert "ticker" not in rendered


def test_private_registry_metrics_http_server_has_a_clean_lifecycle() -> None:
    metrics = OperationalMetrics(service="dispatcher-http-test")
    metrics.queue_pending_items.labels(queue="refresh_dispatch").set(2)

    server = MetricsHttpServer.start(metrics=metrics, host="127.0.0.1", port=0)
    connection = HTTPConnection("127.0.0.1", server.bound_port, timeout=5)
    try:
        assert server.is_running
        connection.request("GET", "/metrics")
        response = connection.getresponse()
        rendered = response.read().decode()
        assert response.status == 200
        assert (
            't212pi_dispatcher_http_test_queue_pending_items{queue="refresh_dispatch"} 2.0'
            in rendered
        )
        assert "python_gc_objects_collected_total" not in rendered
        assert "process_virtual_memory_bytes" not in rendered
        assert "postgresql://private-user:private-password" not in rendered
    finally:
        connection.close()
        server.close()
        server.close()

    assert not server.is_running


def test_standard_library_logs_share_the_structured_redaction_boundary() -> None:
    output = io.StringIO()
    with redirect_stderr(output):
        configure_logging(service="test", secret_canaries=(CANARY,))
        logging.getLogger("provider").info(
            "provider call %s",
            f"Basic dXNlcjpwYXNz {CANARY}",
            extra={"operation": "account_summary", "api_key": "private-key"},
        )

    event = json.loads(output.getvalue())
    assert event["service"] == "test"
    assert event["operation"] == "account_summary"
    assert event["api_key"] == "[REDACTED]"
    assert CANARY not in output.getvalue()
    assert "dXNlcjpwYXNz" not in output.getvalue()
