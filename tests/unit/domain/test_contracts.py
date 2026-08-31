from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from trading212_domain import (
    PHASE_1_CALCULATION_REGISTRY,
    BrokerAccountId,
    CashFlow,
    CashFlowClassification,
    CashFlowId,
    Coverage,
    CurrencyCode,
    DataQuality,
    DiscrepancyId,
    DiscrepancySeverity,
    DiscrepancyType,
    DomainError,
    DomainWarning,
    ErrorCode,
    IngestionRunId,
    Instant,
    Money,
    OwnerId,
    ProvenanceReference,
    QualityState,
    ReconciliationDiscrepancy,
    ReconciliationRunId,
    ResolutionState,
    SourceRecordId,
    TransactionId,
    TransactionType,
    ValueOrigin,
    build_synthetic_identity,
    canonical_json,
    to_primitive,
)

pytestmark = pytest.mark.unit

T0 = Instant.parse("2026-01-01T00:00:00Z")
T1 = Instant.parse("2026-01-02T00:00:00Z")


def test_domain_errors_support_standard_exception_traceback_lifecycle() -> None:
    error = DomainError(ErrorCode.VALIDATION_FAILED, "safe failure")
    error.__traceback__ = None
    with pytest.raises(DomainError, match="safe failure"):
        raise error


def test_quality_states_are_distinct_and_fresh_is_strict() -> None:
    assert len(set(QualityState)) == 6
    complete = Coverage(T0, T1, complete=True)
    quality = DataQuality(QualityState.FRESH, T1, 3600, complete)
    assert quality.state is QualityState.FRESH
    with pytest.raises(DomainError, match="fresh quality"):
        DataQuality(
            QualityState.FRESH,
            T1,
            3600,
            complete,
            warnings=(DomainWarning("stale", "Source is stale"),),
        )


def test_missing_is_distinct_from_zero_in_serialized_contract() -> None:
    payload = to_primitive(
        {
            "missing": None,
            "zero": Money.parse("0", "EUR"),
            "empty": [],
        }
    )
    assert payload == {
        "empty": [],
        "missing": None,
        "zero": {"amount": "0", "currency": "EUR"},
    }


def test_canonical_serialization_is_stable_and_rejects_float_graphs() -> None:
    fixture = build_synthetic_identity()
    first = canonical_json(fixture.account)
    second = canonical_json(fixture.account)
    assert first == second
    assert '"base_currency":"EUR"' in first
    assert ".0" not in first
    with pytest.raises(DomainError, match="binary floats"):
        canonical_json({"unsafe": 0.1})


def test_synthetic_fixture_has_deterministic_ids_and_only_opaque_secret_reference() -> None:
    first = build_synthetic_identity()
    second = build_synthetic_identity()
    assert first == second
    assert isinstance(first.owner.id, UUID)
    assert "no-secret" in first.connection.credential_reference
    assert "credential_reference" not in canonical_json(first.connection)
    assert "api_key" not in canonical_json(first)
    assert "api_secret" not in canonical_json(first)


def test_external_cash_flow_classification_is_frozen() -> None:
    account_id = BrokerAccountId(UUID("10000000-0000-0000-0000-000000000001"))
    cash_flow_id = CashFlowId(UUID("20000000-0000-0000-0000-000000000001"))
    transaction_id = TransactionId(UUID("20000000-0000-0000-0000-000000000002"))
    provenance = ProvenanceReference(
        (SourceRecordId(UUID("30000000-0000-0000-0000-000000000001")),),
        "fixture-v1",
        ValueOrigin.NORMALIZED_PROVIDER,
    )
    deposit = CashFlow(
        cash_flow_id,
        account_id,
        transaction_id,
        CashFlowClassification.EXTERNAL,
        TransactionType.DEPOSIT,
        Money.parse("100", "EUR"),
        T0,
        QualityState.FRESH,
        provenance,
    )
    assert deposit.amount.amount == Decimal(100)
    with pytest.raises(DomainError, match="must be external"):
        CashFlow(
            cash_flow_id,
            account_id,
            transaction_id,
            CashFlowClassification.INTERNAL,
            TransactionType.WITHDRAWAL,
            Money.parse("-10", "EUR"),
            T0,
            QualityState.FRESH,
            provenance,
        )
    with pytest.raises(DomainError, match="not external"):
        CashFlow(
            cash_flow_id,
            account_id,
            transaction_id,
            CashFlowClassification.EXTERNAL,
            TransactionType.DIVIDEND,
            Money.parse("2", "EUR"),
            T0,
            QualityState.FRESH,
            provenance,
        )


def test_reconciliation_discrepancy_preserves_exact_optional_values() -> None:
    discrepancy = ReconciliationDiscrepancy(
        id=DiscrepancyId(UUID("40000000-0000-0000-0000-000000000001")),
        reconciliation_run_id=ReconciliationRunId(UUID("50000000-0000-0000-0000-000000000001")),
        broker_account_id=BrokerAccountId(UUID("60000000-0000-0000-0000-000000000001")),
        discrepancy_type=DiscrepancyType.CASH_MISMATCH,
        severity=DiscrepancySeverity.ERROR,
        resolution_state=ResolutionState.OPEN,
        first_seen_at=T0,
        last_seen_at=T1,
        expected_value=Decimal("100.000000000000000001"),
        observed_value=Decimal("99.999999999999999999"),
        residual=Decimal("0.000000000000000002"),
        tolerance=Decimal("0.000000000000000001"),
        downstream_effect="Portfolio accounting is unreconciled.",
        currency=CurrencyCode("EUR"),
    )
    assert discrepancy.residual == Decimal("0.000000000000000002")


def test_calculation_registry_is_stable_and_default_deny() -> None:
    ids = tuple(item.calculation_id for item in PHASE_1_CALCULATION_REGISTRY.all())
    assert ids == (
        "direct_allocation",
        "performance_summary",
        "portfolio_snapshot",
        "reconciliation",
    )
    with pytest.raises(DomainError, match="unknown calculation"):
        PHASE_1_CALCULATION_REGISTRY.get("language_model_arithmetic")


@pytest.mark.parametrize("unused", [date(2026, 1, 1), OwnerId, IngestionRunId])
def test_imported_contract_symbols_remain_available(unused: object) -> None:
    assert unused is not None
