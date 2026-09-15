"""Independent saved-byte, source-lifetime and fail-before-decode regressions."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session
from trading212_analytics.xray import calculate_xray
from trading212_application import research as app
from trading212_domain.xray import XrayReferenceKind, XraySourceDependency
from trading212_domain.xray_codec import (
    decode_xray_component,
    encode_xray_component,
    encode_xray_input,
    encode_xray_policy,
    encode_xray_result,
)
from trading212_persistence import research_xray_read as module
from trading212_persistence.report_authorization import ReportAuthorization

from tests.unit.analytics.xray_factories import AT, Builder, uid

pytestmark = pytest.mark.unit


def authority() -> ReportAuthorization:
    return ReportAuthorization(
        principal_id=uid(51),
        owner_id=uid(1),
        account_id=uid(2),
        required_scopes=app.RESEARCH_READ_SCOPES,
        expires_at=AT.value + timedelta(days=60),
        issuer="local.synthetic",
        subject="research-fixture",
    )


def source_metadata() -> dict[str, object]:
    created = AT.value - timedelta(days=10)
    return {
        "provider_id": str(uid(900)),
        "license_id": str(uid(999)),
        "pinned_id": str(uid(999)),
        "current_id": str(uid(998)),
        "pinned_store": "allowed",
        "pinned_display": "allowed",
        "pinned_days": 60,
        "current_store": "allowed",
        "current_display": "allowed",
        "current_days": 30,
        "pinned_effective": (created - timedelta(days=1)).isoformat(),
        "current_effective": (created - timedelta(days=1)).isoformat(),
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(days=30)).isoformat(),
    }


@pytest.mark.parametrize(
    "field,value",
    (
        ("pinned_store", "denied"),
        ("pinned_display", "unknown"),
        ("current_store", "unknown"),
        ("current_display", "denied"),
        ("pinned_days", None),
        ("current_days", None),
        ("current_id", None),
        ("pinned_id", str(uid(997))),
        ("current_effective", (AT.value + timedelta(seconds=1)).isoformat()),
    ),
)
def test_every_pinned_and_current_permission_is_required(field: str, value: object) -> None:
    row = source_metadata()
    row[field] = value
    with pytest.raises(app.ResearchServiceError) as error:
        module._deadline(row, AT.value)
    assert error.value.code is app.ResearchErrorCode.SOURCE_UNAVAILABLE


def test_original_clock_does_not_refresh_from_new_xray_or_read_time() -> None:
    row = source_metadata()
    expected = AT.value + timedelta(days=20)
    assert module._deadline(row, AT.value) == expected
    assert module._deadline(row, AT.value + timedelta(days=19)) == expected
    row["current_days"] = 1
    with pytest.raises(app.ResearchServiceError):
        module._deadline(row, AT.value)
    row = source_metadata()
    with pytest.raises(app.ResearchServiceError):
        module._deadline(row, expected)
    assert module._deadline({"provider_id": None, "license_id": None}, AT.value) is None


@pytest.mark.parametrize(
    "head",
    (
        {"admitted": False},
        {"admitted": True, "valid": False},
    ),
)
def test_admission_and_metadata_denial_do_not_fetch_or_decode(
    monkeypatch: pytest.MonkeyPatch,
    head: dict[str, object],
) -> None:
    session = Mock(spec=Session)
    session.execute.return_value.mappings.return_value = iter(
        [
            {"ordinal": 0, "metadata": head},
        ]
    )
    decode = Mock(side_effect=AssertionError("denied private decode"))
    monkeypatch.setattr(module, "decode_xray_input", decode)
    with pytest.raises(app.ResearchServiceError):
        module.read_research_xray(session, authority(), uid(40), now=AT.value)
    assert session.execute.call_count == 1
    decode.assert_not_called()


def saved_cash() -> tuple[module._Metadata, list[dict[str, object]], bytes]:
    builder = Builder()
    builder.cash_row("100")
    value = builder.finish()
    result = calculate_xray(value)
    encoded_input, encoded_result = encode_xray_input(value), encode_xray_result(result)
    encoded_policy = encode_xray_policy(value.policy)
    encoded_summary = encode_xray_component(result.portfolio_summary)
    reference = value.source_dependencies[0]
    encoded_reference = encode_xray_component(reference)
    dependency = module._Dependency(
        id=uid(45),
        reference_id=reference.id,
        target="valuation_run_id",
        target_id=uid(46),
        provider_id=None,
        license_id=None,
        content_digest=None,
        payload_bytes=len(encoded_reference),
        fingerprint="c" * 64,
        deadline=None,
    )
    metadata = module._Metadata(
        run_id=uid(40),
        input_id=uid(41),
        analytics_id=uid(42),
        owner_id=value.owner_id,
        account_id=value.account_id,
        snapshot_id=value.snapshot_id,
        valuation_run_id=uid(46),
        policy_id=value.policy.id,
        input_digest=sha256(encoded_input).hexdigest(),
        result_digest=sha256(encoded_result).hexdigest(),
        policy_digest=sha256(encoded_policy).hexdigest(),
        currency=value.reporting_currency.value,
        valuation_at=value.valuation_at.value,
        cutoff_at=value.source_cutoff_at.value,
        method_version=value.policy.method_version,
        input_bytes=len(encoded_input),
        result_bytes=len(encoded_result),
        policy_bytes=len(encoded_policy),
        summary_bytes=len(encoded_summary),
        fingerprint="d" * 64,
        dependencies=(dependency,),
        deadline=None,
    )
    payloads = [
        {"kind": "input", "id": metadata.input_id, "payload": encoded_input},
        {"kind": "result", "id": metadata.run_id, "payload": encoded_result},
        {"kind": "policy", "id": metadata.policy_id, "payload": encoded_policy},
        {"kind": "summary", "id": metadata.run_id, "payload": encoded_summary},
        {"kind": "dependency", "id": dependency.id, "payload": encoded_reference},
    ]
    return metadata, payloads, encoded_result


def test_full_saved_result_is_preserved_without_recalculation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata, payloads, original = saved_cash()
    session = Mock(spec=Session)
    session.execute.return_value.mappings.return_value = iter(payloads)
    monkeypatch.setattr(module, "_metadata", lambda *args, **kwargs: metadata)
    monkeypatch.setattr(
        "trading212_analytics.xray.calculate_xray",
        Mock(side_effect=AssertionError("recalculation")),
    )
    basis = module.read_research_xray(session, authority(), metadata.run_id, now=AT.value)
    assert encode_xray_result(basis.result) == original
    assert basis.pin.result_digest == sha256(original).hexdigest()
    assert basis.result.portfolio_summary.total.value is not None
    assert basis.result.portfolio_summary.total.value.amount == 100
    assert basis.deadline is None
    module.finish_research_xray(session, authority(), basis, now=AT.value)
    assert session.execute.call_count == 1  # payload query; metadata deliberately stubbed


@pytest.mark.parametrize("fault", ("duplicate", "foreign", "missing", "digest"))
def test_payload_union_never_accepts_extra_missing_or_changed_proof(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    metadata, payloads, _ = saved_cash()
    if fault == "duplicate":
        payloads.append(payloads[-1])
    elif fault == "foreign":
        payloads[-1] = {**payloads[-1], "id": uid(9990)}
    elif fault == "missing":
        payloads.pop()
    else:
        original = payloads[1]["payload"]
        assert isinstance(original, bytes)
        payloads[1] = {**payloads[1], "payload": b"x" * len(original)}
    session = Mock(spec=Session)
    session.execute.return_value.mappings.return_value = iter(payloads)
    monkeypatch.setattr(module, "_metadata", lambda *args, **kwargs: metadata)
    decode = Mock(side_effect=AssertionError("invalid private input must not decode"))
    monkeypatch.setattr(module, "decode_xray_input", decode)
    with pytest.raises(app.ResearchServiceError):
        module.read_research_xray(session, authority(), metadata.run_id, now=AT.value)
    decode.assert_not_called()


@pytest.mark.parametrize("fault", ("parent", "reference_id", "account", "target_kind"))
def test_typed_physical_reference_must_match_normalized_owned_parent(fault: str) -> None:
    metadata, payloads, _ = saved_cash()
    raw = payloads[-1]["payload"]
    assert isinstance(raw, bytes)
    value = decode_xray_component(raw, XraySourceDependency)
    if fault == "parent":
        value = replace(
            value,
            snapshot_id=uid(801),
            reference=replace(value.reference, parent_record_id=uid(801)),
        )
    elif fault == "reference_id":
        value = replace(value, id=uid(802))
    elif fault == "account":
        value = replace(value, account_id=uid(803))
    else:
        value = replace(
            value,
            reference=replace(
                value.reference,
                kind=XrayReferenceKind.BROKER_SOURCE_RECORD,
                parent_record_id=value.account_id,
            ),
        )
    with pytest.raises(app.ResearchServiceError):
        module._reference(metadata, metadata.dependencies[0], value)
