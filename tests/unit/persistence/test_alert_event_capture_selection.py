"""Scope canonical broker revision groups before ambiguity, quality and FX gates."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session
from trading212_analytics._historical_core import (
    revision_first_eligible_at,
    selected_event_revisions,
)
from trading212_domain import alerts as d
from trading212_domain import historical as h
from trading212_domain.alert_serialization import alert_record_digest
from trading212_domain.enums import QualityState
from trading212_domain.values import Money
from trading212_persistence import alert_capture_events as events
from trading212_persistence.activity_revision_store import (
    activity_revision_sources,
    apply_revision_evidence,
)
from trading212_persistence.alert_capture_common import AlertCaptureState, AlertCaptureUnavailable
from trading212_persistence.historical_normalization import normalize_record
from trading212_persistence.models import SourceRecordModel
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.source_models import MarketDataInstrumentModel
from trading212_persistence.source_service import PostgresSourceService

from tests.unit.analytics.alert_factories import AT, EUR, capture, predicate, uid
from tests.unit.persistence.test_activity_revisions import proof
from tests.unit.persistence.test_historical_normalization import execution

pytestmark = pytest.mark.unit
START = AT - timedelta(minutes=5)


def record(
    number: int,
    reference: str,
    *,
    dividend: bool = False,
    amount: str = "10",
    currency: str = "EUR",
    kind: str = "DEPOSIT",
    ticker: str = "A",
    known: datetime = AT - timedelta(seconds=1),
    economic: datetime = AT - timedelta(seconds=2),
) -> SourceRecordModel:
    return SourceRecordModel(
        id=uid(number),
        capability="historical_dividends" if dividend else "historical_transactions",
        provider_record_id=reference,
        source_updated_at=economic,
        observed_at=known,
        created_at=known,
        payload_fingerprint=str(number % 10) * 64,
        sanitized_payload={
            "reference": reference,
            "paidOn" if dividend else "dateTime": economic.isoformat(),
            "amount": {"$decimal": amount},
            "currency": currency,
            "type": kind,
            "ticker": ticker,
        },
    )


def mappings() -> tuple[MarketDataInstrumentModel, ...]:
    return tuple(
        MarketDataInstrumentModel(
            id=uid(number + 10),
            provider_key=ticker,
            instrument_id=uid(number),
            listing_id=uid(number + 20),
            state="resolved",
            created_at=AT - timedelta(days=10),
            valid_from=AT - timedelta(days=10),
            content_digest="a" * 64,
        )
        for number, ticker in ((100, "A"), (200, "B"))
    )


def state(
    monkeypatch: pytest.MonkeyPatch,
    selected: d.AlertPredicate,
    records: tuple[SourceRecordModel, ...] = (),
) -> AlertCaptureState:
    session = Mock(spec=Session)
    session.scalars.side_effect = [records, mappings(), ()]
    version = capture(selected.metric).version
    definition = replace(version.definition, predicate=selected)
    version = replace(
        version, definition=definition, content_digest=alert_record_digest(definition)
    )
    monkeypatch.setattr(
        events, "capture_activity_revisions", lambda *args, **kw: (kw["events"], ())
    )
    monkeypatch.setattr(events, "_coverage", lambda *args: True)
    return AlertCaptureState(
        cast(Session, session),
        cast(ReportAuthorization, Mock()),
        version,
        AT,
        d.AlertObservationWindow(
            start_at=START,
            end_at=AT,
            newly_known_revisions=selected.metric is not d.AlertMetric.ACTIVITY_COUNT,
        ),
        now=AT,
        sources=cast(PostgresSourceService, Mock()),
    )


def test_old_unrelated_conflict_does_not_hide_current_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        record(1, "old-payment", dividend=True, amount="2", known=START, economic=START),
        record(2, "old-payment", dividend=True, amount="3", known=START, economic=START),
        record(3, "current-deposit"),
    )
    actual = events.capture_activity(
        state(monkeypatch, predicate(d.AlertMetric.ACTIVITY_COUNT), rows)
    )
    assert isinstance(actual, d.AlertThresholdInput)
    assert actual.observation.observed.value == 1


@pytest.mark.parametrize("scope", ["window", "instrument", "kind"])
def test_relevant_group_keeps_conflicting_members_outside_individual_filter(
    monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    selected = predicate(d.AlertMetric.POSITIVE_DIVIDEND)
    if scope == "kind":
        selected = replace(
            predicate(d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT),
            activity_kind=h.HistoricalCashFlowKind.DEPOSIT,
        )
        rows = (record(1, "same"), record(2, "same", kind="WITHDRAW", amount="-10"))
    else:
        selected = replace(selected, instrument_id=uid(100))
        rows = (
            record(1, "same", dividend=True),
            record(
                2,
                "same",
                dividend=True,
                amount="11",
                known=START if scope == "window" else AT,
                ticker="B" if scope == "instrument" else "A",
            ),
        )
    with pytest.raises(AlertCaptureUnavailable) as caught:
        events.capture_activity(state(monkeypatch, selected, rows))
    assert caught.value.reason is d.AlertReason.AMBIGUOUS_SOURCE


def test_known_other_instrument_conflict_is_irrelevant_but_unknown_identity_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = replace(predicate(d.AlertMetric.POSITIVE_DIVIDEND), instrument_id=uid(100))
    rows = (
        record(1, "other", dividend=True, ticker="B"),
        record(2, "other", dividend=True, ticker="B", amount="11"),
        record(3, "selected", dividend=True),
    )
    actual = events.capture_activity(state(monkeypatch, selected, rows))
    assert isinstance(actual, d.AlertEventBatchInput)
    assert [item.revision_id for item in actual.events] == [uid(3)]
    with pytest.raises(AlertCaptureUnavailable) as caught:
        events.capture_activity(
            state(monkeypatch, selected, (record(4, "unknown", dividend=True, ticker="UNKNOWN"),))
        )
    assert caught.value.reason is d.AlertReason.UNKNOWN_IDENTITY


def test_late_known_proof_retains_old_economic_correction_and_all_revision_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = normalize_record(
        record(1, "same", dividend=True, known=START, economic=START, amount="2"), None, mappings()
    )
    revised = normalize_record(
        record(2, "same", dividend=True, known=START, economic=START, amount="3"), None, mappings()
    )
    assert isinstance(previous, h.HistoricalDividend) and isinstance(revised, h.HistoricalDividend)
    evidence = proof(revised, previous)
    actual = state(monkeypatch, predicate(d.AlertMetric.POSITIVE_DIVIDEND))
    assert events._relevant_revisions(actual, (previous, revised)) == ()
    overlaid = apply_revision_evidence((previous, revised), (evidence,), cutoff=AT)
    assert overlaid == (previous, revised)
    sources = activity_revision_sources((evidence,))
    eligible = revision_first_eligible_at(overlaid, sources, cutoff=AT)
    relevant = events._relevant_revisions(actual, overlaid, eligible)
    assert len(relevant) == 2
    selected, ambiguous = selected_event_revisions(relevant, AT, revision_sources=sources)
    assert not ambiguous and len(selected) == 1
    assert selected[0].identity.revision_id == str(uid(2))
    assert selected[0].identity.first_observed_at == START
    assert eligible[selected[0].identity.source_record_id] == AT
    assert selected[0].identity.economic_at == START


@pytest.mark.parametrize(
    "metric", [d.AlertMetric.ACTIVITY_COUNT, d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT]
)
def test_wrong_kind_does_not_poison_quality_or_require_foreign_fx(
    monkeypatch: pytest.MonkeyPatch, metric: d.AlertMetric
) -> None:
    selected = replace(predicate(metric), activity_kind=h.HistoricalCashFlowKind.DEPOSIT)
    actual = state(monkeypatch, selected)
    deposit = normalize_record(record(1, "deposit"), None, ())
    withdrawal = normalize_record(
        record(2, "withdrawal", kind="WITHDRAW", currency="USD"), None, ()
    )
    assert deposit is not None and withdrawal is not None
    withdrawal = replace(
        withdrawal, identity=replace(withdrawal.identity, quality=QualityState.FAILED)
    )
    # Isolate the post-selection material gate using canonical normalized values.
    monkeypatch.setattr(
        events,
        "_sources",
        lambda *args: (
            (deposit, withdrawal),
            {
                item.identity.source_record_id: item.identity.first_observed_at
                for item in (deposit, withdrawal)
            },
        ),
    )
    result = events.capture_activity(actual)
    assert actual.context.quality is QualityState.FRESH and actual.fx_conversions == []
    if isinstance(result, d.AlertThresholdInput):
        assert result.observation.observed.value == 1
    else:
        assert len(result.events) == 1
        assert result.events[0].net_amount == Money(Decimal("10"), EUR)


def test_kind_filter_retains_linked_parent_so_cash_effect_is_not_counted_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = execution(net="21", taxes="0")
    parent = replace(
        parent, identity=replace(parent.identity, economic_at=AT, first_observed_at=AT)
    )
    fee = normalize_record(record(9, "fee", kind="FEE", amount="1", economic=AT), None, ())
    assert isinstance(fee, h.HistoricalCashEffect)
    fee = replace(fee, related_event_keys=(parent.identity.economic_key,))
    actual = state(
        monkeypatch,
        replace(
            predicate(d.AlertMetric.ACTIVITY_COUNT), activity_kind=h.HistoricalCashFlowKind.FEE
        ),
    )
    relevant = events._relevant_revisions(actual, (parent, fee))
    assert relevant == (parent, fee)
    selected, ambiguous = selected_event_revisions(relevant, AT)
    assert not ambiguous and selected == (parent,)
    assert not any(events._in_scope(actual, item) for item in selected)
