"""Capture bounds produce a replayable unavailable slot without a truncated prefix."""

from datetime import timedelta
from typing import cast
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_application.sources import SourceServiceError, SourceServiceErrorCode
from trading212_domain import alerts as d
from trading212_domain.alert_serialization import decode_alert_input, encode_alert_input
from trading212_domain.reports import ReportSourceKind
from trading212_persistence import alert_capture as capture_module
from trading212_persistence.alert_capture_common import AlertCaptureBound, AlertCaptureState
from trading212_persistence.report_authorization import ReportAuthorization

from tests.unit.analytics.alert_factories import AT, capture, uid

pytestmark = pytest.mark.unit


def _capture(monkeypatch: pytest.MonkeyPatch) -> capture_module.CanonicalAlertCapture:
    version = capture().version
    session = Mock(spec=Session)
    session.scalar.return_value = Mock(
        version_id=version.id,
        lifecycle="active",
        occurred_at=AT - timedelta(minutes=5),
        id=uid(50),
    )
    authorization = Mock(spec=ReportAuthorization)
    authorization.owner_id, authorization.account_id = version.owner_id, version.account_id
    monkeypatch.setattr(capture_module, "validate_alert_references", lambda *args, **kwargs: None)
    return capture_module.CanonicalAlertCapture(
        cast(Session, session),
        cast(ReportAuthorization, authorization),
        now=AT,
        cursor_signing_key=b"synthetic-capture-limit-cursor-key",
        sessions=cast(sessionmaker[Session], Mock()),
    )


def _reference(state: AlertCaptureState, number: int) -> None:
    state.reference(
        kind=ReportSourceKind.BROKER_SOURCE_RECORD,
        identifier=uid(number),
        digest="a" * 64,
        effective_at=AT,
        known_at=AT,
    )


@pytest.mark.parametrize("kind", ["rows", "bytes", "references"])
def test_overflow_keeps_exact_slot_and_reason_without_partial_evidence(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    adapter = _capture(monkeypatch)

    def source(
        self: capture_module.CanonicalAlertCapture, state: AlertCaptureState
    ) -> d.AlertThresholdInput:
        count = (
            6000
            if kind == "bytes"
            else d.MAX_ALERT_SOURCE_REFERENCES + 1
            if kind == "references"
            else 1
        )
        for number in range(100, 100 + count):
            _reference(state, number)
        if kind == "rows":
            raise AlertCaptureBound("complete universe exceeded its bound")
        return d.AlertThresholdInput(observation=state.observation(1))

    # Use an integer metric so the synthetic source only tests the capture envelope.
    version = capture(d.AlertMetric.ACTIVITY_COUNT).version
    monkeypatch.setattr(capture_module.CanonicalAlertCapture, "_capture", source)
    result = adapter.capture_evaluation(version, AT, d.AlertExecutionIntent.LIVE)
    assert result.scheduled_for == result.source_cutoff_at == AT
    assert isinstance(result.payload, d.AlertThresholdInput)
    assert result.payload.observation.observed.reason is d.AlertReason.INPUT_BOUND_EXCEEDED
    assert result.payload.observation.observed.value is None
    assert result.payload.observation.observed.quality == result.contexts[0].quality
    assert not result.source_references and not result.canonical_bindings and not result.licenses
    assert decode_alert_input(encode_alert_input(result)) == result


@pytest.mark.parametrize(
    "code,reason,retained",
    [
        (SourceServiceErrorCode.ACCESS_DENIED, d.AlertReason.SOURCE_RESTRICTED, False),
        (SourceServiceErrorCode.RESULT_TOO_LARGE, d.AlertReason.INPUT_BOUND_EXCEEDED, False),
        (SourceServiceErrorCode.NOT_FOUND, d.AlertReason.MISSING_INPUT, True),
        (SourceServiceErrorCode.SOURCE_REVISION_CONFLICT, d.AlertReason.AMBIGUOUS_SOURCE, True),
    ],
)
def test_fixed_source_failure_categories_are_inspectable_without_raw_error_text(
    monkeypatch: pytest.MonkeyPatch,
    code: SourceServiceErrorCode,
    reason: d.AlertReason,
    retained: bool,
) -> None:
    adapter = _capture(monkeypatch)

    def source(
        self: capture_module.CanonicalAlertCapture, state: AlertCaptureState
    ) -> d.AlertThresholdInput:
        _reference(state, 100)
        raise SourceServiceError(code, "private-source-error-canary")

    monkeypatch.setattr(capture_module.CanonicalAlertCapture, "_capture", source)
    result = adapter.capture_evaluation(capture().version, AT, d.AlertExecutionIntent.LIVE)
    assert isinstance(result.payload, d.AlertThresholdInput)
    assert result.payload.observation.observed.reason is reason
    assert bool(result.source_references) is retained
    assert b"private-source-error-canary" not in encode_alert_input(result)
