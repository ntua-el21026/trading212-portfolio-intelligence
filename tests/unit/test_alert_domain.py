import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from trading212_analytics.alerts import evaluate_alert
from trading212_application.alerts import AlertPageQuery, alert_required_scopes
from trading212_domain import alerts as a
from trading212_domain.alert_serialization import (
    alert_record_digest,
    decode_alert_input,
    decode_alert_record,
    decode_alert_result,
    decode_alert_rule_definition,
    encode_alert_input,
    encode_alert_record,
    encode_alert_result,
    encode_alert_rule_definition,
)
from trading212_domain.errors import DomainError, ErrorCode
from trading212_domain.reports import ReportSourceKind
from trading212_domain.sources import LicensePermission, SourceLicense
from trading212_domain.values import CurrencyCode, Money
from trading212_security.principals import Scope

from tests.unit.analytics.alert_factories import AT, capture, predicate, uid

pytestmark = pytest.mark.unit


def _fx_input(*, broker: bool) -> a.AlertEvaluationInput:
    usd, eur = CurrencyCode("USD"), CurrencyCode("EUR")
    source = a.AlertSourceReference(
        key="selected-fx",
        kind=ReportSourceKind.BROKER_SOURCE_RECORD if broker else ReportSourceKind.FX_OBSERVATION,
        subject_id=uid(601),
        content_digest="a" * 64,
        effective_at=AT,
        first_observed_at=AT,
        parent_id=None if broker else uid(602),
        provider_id=None if broker else uid(603),
        license_version_id=None if broker else uid(604),
    )
    license = SourceLicense(
        id=str(uid(604)),
        provider_id=str(uid(603)),
        version="v1",
        effective_at=AT,
        store=LicensePermission.ALLOWED,
        display=LicensePermission.ALLOWED,
        report=LicensePermission.ALLOWED,
        export=LicensePermission.ALLOWED,
        retention_days=90,
        attribution="Synthetic FX",
        evidence_key="synthetic-fx",
    )
    leg = a.AlertFxLeg(
        base=usd,
        quote=eur,
        rate=Decimal("0.8"),
        source_reference_key=source.key,
        snapshot_id=source.parent_id,
        provider_id=source.provider_id,
        observed_at=AT,
    )
    conversion = a.AlertMoneyConversion(
        original=Money(Decimal("62.5"), usd),
        reporting_currency=eur,
        converted=Money(Decimal("50"), eur),
        comparison_basis=Decimal("50"),
        legs=(leg,),
    )
    return replace(
        capture(),
        source_references=(source,),
        licenses=() if broker else (license,),
        fx_conversions=(conversion,),
    )


@pytest.mark.parametrize("broker", (False, True))
def test_fx_conversion_retains_exact_market_or_broker_source_without_fabricated_parent(
    broker: bool,
) -> None:
    value = _fx_input(broker=broker)
    assert decode_alert_input(encode_alert_input(value)) == value
    leg = value.fx_conversions[0].legs[0]
    assert (leg.snapshot_id is None) is broker
    assert (leg.provider_id is None) is broker
    assert value.fx_conversions[0].converted == Money(Decimal("50"), CurrencyCode("EUR"))


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_source",
        "wrong_time",
        "wrong_kind",
        "fabricated_parent",
        "fabricated_provider",
        "market_null_ids",
        "market_missing_license",
    ),
)
def test_fx_conversion_rejects_unbound_or_falsely_typed_source(mutation: str) -> None:
    value = _fx_input(broker=not mutation.startswith("market_"))
    source = value.source_references[0]
    conversion = value.fx_conversions[0]
    leg = conversion.legs[0]
    with pytest.raises(DomainError):
        if mutation == "missing_source":
            value = replace(value, source_references=())
        elif mutation == "wrong_time":
            value = replace(
                value, source_references=(replace(source, effective_at=AT - timedelta(seconds=1)),)
            )
        elif mutation == "wrong_kind":
            value = replace(
                value,
                source_references=(replace(source, kind=ReportSourceKind.PORTFOLIO_SNAPSHOT),),
            )
        elif mutation == "fabricated_parent":
            value = replace(value, source_references=(replace(source, parent_id=uid(602)),))
        elif mutation == "fabricated_provider":
            value = replace(value, source_references=(replace(source, provider_id=uid(603)),))
        elif mutation == "market_null_ids":
            value = replace(
                value,
                fx_conversions=(
                    replace(conversion, legs=(replace(leg, snapshot_id=None, provider_id=None),)),
                ),
            )
        else:
            value = replace(
                value, licenses=(), source_references=(replace(source, license_version_id=None),)
            )


def test_broker_fx_cannot_fake_common_snapshot_for_two_leg_triangulation() -> None:
    value = _fx_input(broker=True)
    conversion = value.fx_conversions[0]
    first = conversion.legs[0]
    second = replace(
        first,
        base=CurrencyCode("EUR"),
        quote=CurrencyCode("GBP"),
        source_reference_key="another-broker-record",
    )
    with pytest.raises(DomainError):
        replace(
            conversion,
            reporting_currency=CurrencyCode("GBP"),
            converted=Money(Decimal("40"), CurrencyCode("GBP")),
            comparison_basis=Decimal("40"),
            legs=(first, second),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "float",
        "unknown",
        "duplicate",
        "integer_decimal",
        "unknown_family",
        "noncanonical_decimal",
        "irrelevant",
        "missing_required",
    ),
)
def test_closed_rule_codec_rejects_ambiguous_or_irrelevant_input(mutation: str) -> None:
    definition = capture().version.definition
    raw = encode_alert_rule_definition(definition)
    value = json.loads(raw)
    if mutation == "float":
        value["predicate"]["threshold"] = 0.1
    elif mutation == "integer_decimal":
        value["predicate"]["threshold"] = 1
    elif mutation == "unknown":
        value["expression"] = "arbitrary"
    elif mutation == "unknown_family":
        value["predicate"]["family"] = "made_up"
    elif mutation == "noncanonical_decimal":
        value["predicate"]["threshold"] = "0.10"
    elif mutation == "irrelevant":
        value["predicate"]["entity_id"] = str(uid(99))
    elif mutation == "missing_required":
        del value["predicate"]["metric"]
    if mutation == "duplicate":
        raw = raw.replace(b'"name":', b'"name":"first","name":', 1)
    else:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(DomainError):
        decode_alert_rule_definition(raw)


def test_rule_version_digest_and_temporal_input_bindings_reject_fabricated_history() -> None:
    value = capture()
    with pytest.raises(DomainError):
        replace(value.version, content_digest="a" * 64)
    with pytest.raises(DomainError):
        replace(value, version=replace(value.version, created_at=AT + timedelta(seconds=1)))
    with pytest.raises(DomainError):
        replace(value, contexts=(replace(value.contexts[0], account_id=uid(99)),))
    with pytest.raises(DomainError):
        replace(value, contexts=(replace(value.contexts[0], source_reference_keys=("missing",)),))
    source = a.AlertSourceReference(
        key="future",
        kind=ReportSourceKind.PORTFOLIO_SNAPSHOT,
        subject_id=uid(9),
        content_digest="a" * 64,
        effective_at=AT,
        first_observed_at=AT + timedelta(microseconds=1),
    )
    with pytest.raises(DomainError):
        replace(value, source_references=(source,))


def test_input_and_result_bytes_fail_whole_document_at_two_mib() -> None:
    value = capture()
    contexts = tuple(
        replace(value.contexts[0], key=f"context-{index}", assumptions=("X" * 2000,) * 8)
        for index in range(256)
    )
    value = replace(value, contexts=(value.contexts[0], *contexts[:255]))
    with pytest.raises(DomainError) as caught:
        encode_alert_input(value)
    assert caught.value.code is ErrorCode.INPUT_BOUND_EXCEEDED
    with pytest.raises(DomainError):
        decode_alert_input(b" " * (a.MAX_ALERT_INPUT_BYTES + 1))
    result = evaluate_alert(capture())
    with pytest.raises(DomainError):
        encode_alert_result(replace(result, contexts=value.contexts))


def test_ratio_basis_is_exclusively_private_xray_and_general_scalar_cannot_disagree() -> None:
    value = capture()
    assert isinstance(value.payload, a.AlertThresholdInput)
    with pytest.raises(DomainError):
        replace(value.payload.observation, comparison_basis=Decimal("0.6"))
    with pytest.raises(DomainError):
        replace(
            value.payload.observation,
            comparison_basis=a.AlertRatioBasis(numerator=Decimal(1), denominator=Decimal(2)),
        )
    with pytest.raises(DomainError):
        a.AlertRatioBasis(
            numerator=Decimal(1),
            denominator=Decimal(2),
            numeric_policy_version="alert_decimal256_exact_q18_v1",
        )
    with pytest.raises(DomainError):
        a.AlertRatioBasis(numerator=Decimal("1e232"), denominator=Decimal(1))


def test_result_payload_has_no_private_coefficients_and_codec_is_exact() -> None:
    result = evaluate_alert(capture())
    encoded = encode_alert_result(result)
    assert b"comparison_basis" not in encoded and b"numerator" not in encoded
    assert decode_alert_result(encoded) == result
    with pytest.raises(DomainError):
        replace(result, decision=False)
    with pytest.raises(DomainError):
        replace(result, contexts=())


def test_context_permutation_canonical_input_and_replay_result_are_identical() -> None:
    value = capture()
    value = replace(value, contexts=(*value.contexts, replace(value.contexts[0], key="other")))
    reverse = replace(value, contexts=tuple(reversed(value.contexts)))
    assert encode_alert_input(value) == encode_alert_input(reverse)
    assert encode_alert_result(evaluate_alert(value)) == encode_alert_result(
        evaluate_alert(reverse)
    )
    assert encode_alert_input(decode_alert_input(encode_alert_input(value))) == encode_alert_input(
        value
    )


def test_exact_10000_event_bound_and_overflow() -> None:
    value = capture(a.AlertMetric.REFRESH_FAILED)
    assert isinstance(value.payload, a.AlertEventBatchInput)
    event = value.payload.events[0]
    events = tuple(replace(event, identity=uid(100 + index)) for index in range(10000))
    assert len(a.AlertEventBatchInput(events=events, complete=True).events) == 10000
    with pytest.raises(DomainError):
        a.AlertEventBatchInput(events=(*events, event), complete=True)
    with pytest.raises(DomainError):
        a.AlertEventBatchInput(events=(event, event), complete=True)


def test_read_and_write_grants_are_independent_and_cursor_bound_is_consistent() -> None:
    assert alert_required_scopes(None, write=False) == frozenset(
        {Scope.PORTFOLIO_READ, Scope.ALERTS_READ}
    )
    value = capture().version.definition
    assert alert_required_scopes(value, write=True) == frozenset(
        {Scope.PORTFOLIO_READ, Scope.ALERTS_WRITE, Scope.ANALYTICS_READ}
    )
    drift = replace(value, predicate=predicate(a.AlertMetric.PORTFOLIO_L1_DRIFT))
    assert Scope.TARGETS_READ in alert_required_scopes(drift, write=True)
    assert Scope.ALERTS_READ not in alert_required_scopes(drift, write=True)
    page = AlertPageQuery(cursor="x" * 2048)
    assert decode_alert_record(encode_alert_record(page), AlertPageQuery) == page
    assert alert_record_digest(value)
