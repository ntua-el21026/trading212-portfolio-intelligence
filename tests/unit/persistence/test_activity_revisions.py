from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from trading212_analytics._historical_core import event_revision_key, selected_event_revisions
from trading212_application import activity_revisions as app
from trading212_domain import Money
from trading212_domain import historical as d
from trading212_persistence.activity_revision_store import (
    activity_revision_sources,
    apply_revision_evidence,
    revision_digest,
)

from tests.unit.analytics.alert_factories import AT, EUR, uid
from tests.unit.analytics.historical_factories import identity, metric

pytestmark = pytest.mark.unit


def dividend(number: int, amount: str) -> d.HistoricalDividend:
    return d.HistoricalDividend(
        identity=identity(number, AT - timedelta(days=1)),
        dividend_key="same-payment",
        instrument_id=None,
        listing_id=None,
        net=Money(Decimal(amount), EUR),
        gross=metric(amount),
        withholding=metric("0"),
        payment_convention="exact_provider_instant",
    )


def proof(
    new: d.HistoricalDividend, previous: d.HistoricalDividend
) -> app.ActivityRevisionEvidence:
    registration = app.ActivityRevisionRegistration(
        id=uid(900),
        new_source_record_id=uid(int(new.identity.source_record_id.replace("-", ""), 16)),
        superseded_source_record_id=uid(
            int(previous.identity.source_record_id.replace("-", ""), 16)
        ),
        authority=app.ActivityRevisionAuthority.OWNER_ATTESTATION,
        evidence_key="explicit-correction-review",
    )
    value = app.ActivityRevisionEvidence(
        registration=registration,
        owner_id=uid(1),
        account_id=uid(2),
        principal_id=uid(3),
        economic_key=event_revision_key(new),
        first_observed_at=AT,
        content_digest="0" * 64,
    )
    return replace(value, content_digest=revision_digest(value))


def test_explicit_revision_proof_preserves_raw_knowledge_and_financial_content() -> None:
    previous, new = dividend(100, "2"), dividend(101, "3")
    # There is no provider revision sequence in broker normalization.
    previous = replace(previous, identity=replace(previous.identity, revision_sequence=None))
    new = replace(new, identity=replace(new.identity, revision_sequence=None))
    evidence = proof(new, previous)
    assert selected_event_revisions((previous, new), AT - timedelta(seconds=1)) == ((), True)
    assert apply_revision_evidence(
        (previous, new), (evidence,), cutoff=AT - timedelta(microseconds=1)
    ) == (previous, new)
    overlaid = apply_revision_evidence((previous, new), (evidence,), cutoff=AT)
    assert overlaid == (previous, new)
    selected, ambiguous = selected_event_revisions(
        overlaid, AT, revision_sources=activity_revision_sources((evidence,))
    )
    assert not ambiguous and len(selected) == 1 and isinstance(selected[0], d.HistoricalDividend)
    assert selected[0].net == new.net and selected[0].gross == new.gross
    assert selected[0].identity.first_observed_at == new.identity.first_observed_at
    assert selected[0].identity.supersedes_revision_id == previous.identity.revision_id
    assert selected[0].correction_of == previous.identity.revision_id
    assert selected[0].identity.revision_sequence is None


def test_proof_content_identity_and_duplicate_edges_fail_closed() -> None:
    previous, new = dividend(100, "2"), dividend(101, "3")
    evidence = proof(new, previous)
    assert apply_revision_evidence((previous, new), (evidence,), cutoff=AT) == (previous, new)
    with pytest.raises(app.ActivityRevisionError):
        apply_revision_evidence(
            (previous, new), (replace(evidence, content_digest="a" * 64),), cutoff=AT
        )
    different = replace(evidence, economic_key="different-economic-payment")
    different = replace(different, content_digest=revision_digest(different))
    with pytest.raises(app.ActivityRevisionError):
        apply_revision_evidence((previous, new), (different,), cutoff=AT)
    with pytest.raises(app.ActivityRevisionError):
        apply_revision_evidence((previous, new), (evidence, evidence), cutoff=AT)
