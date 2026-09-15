"""Private retained codecs preserve complete paths and reject identity/financial forgery."""

import json
from dataclasses import replace
from datetime import date
from decimal import ROUND_DOWN, Context, Decimal, Inexact, Rounded, localcontext
from hashlib import sha256
from typing import Any
from uuid import UUID

import pytest
from trading212_analytics import projection as kernel
from trading212_application.projection_capture import (
    ProjectionAssumptionVersion,
    ProjectionCapturePlan,
    ProjectionDatedEntry,
    ProjectionDatedSchedule,
    ProjectionInitialSelection,
    ProjectionRunSelection,
    projection_definition_digest,
)
from trading212_domain.projection import (
    ProjectionAllocation,
    ProjectionAsset,
    ProjectionAssumptions,
)
from trading212_domain.projection_result import ProjectionCalculation, ProjectionChunk
from trading212_domain.values import CurrencyCode, Money
from trading212_persistence.projection_capture_codec import ProjectionCodecError
from trading212_persistence.projection_retained_codec import (
    ProjectionChunkBytes,
    ProjectionResultBytes,
    pack_projection_chunk,
    pack_projection_result,
    unpack_projection_chunk,
    unpack_projection_result,
)

from tests.unit.persistence.projection_codec_factories import capture

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def retained() -> tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk]:
    plan = capture()
    result = kernel.calculate_projection(plan.inputs)
    chunk = kernel.calculate_projection_chunk(plan.inputs, 1, 2, variant="mean_log_delta")
    return plan, result, chunk


def result_bytes(raw: Any, original: ProjectionResultBytes) -> ProjectionResultBytes:
    payload = json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    return replace(
        original,
        canonical_result=payload,
        byte_length=len(payload),
        content_digest=sha256(payload).hexdigest(),
    )


def chunk_bytes(raw: Any, original: ProjectionChunkBytes) -> ProjectionChunkBytes:
    payload = json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    return replace(
        original,
        canonical_chunk=payload,
        byte_length=len(payload),
        content_digest=sha256(payload).hexdigest(),
    )


def test_result_restores_every_requested_variant_path_point_and_financial_field(
    retained: tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk],
) -> None:
    plan, result, _ = retained
    packed = pack_projection_result(result)
    restored = unpack_projection_result(packed, expected_inputs=plan.inputs)
    assert restored == result
    assert len(restored.variants) == 3
    for original, variant in zip(result.variants, restored.variants, strict=True):
        assert len(variant.paths) == 3
        assert tuple(path.index for path in variant.paths) == (0, 1, 2)
        assert variant.goal == original.goal
        assert variant.nominal_histogram == original.nominal_histogram
        assert variant.real_histogram == original.real_histogram
        for original_path, path in zip(original.paths, variant.paths, strict=True):
            assert len(path.points) == 4
            assert path.points == original_path.points
            assert all(len(point.assets) == 2 for point in path.points)
    assert packed.byte_length == len(packed.canonical_result)
    assert packed.content_digest == sha256(packed.canonical_result).hexdigest()


def test_nonzero_absolute_chunk_range_is_preserved(
    retained: tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk],
) -> None:
    plan, _, chunk = retained
    packed = pack_projection_chunk(chunk, expected_inputs=plan.inputs)
    assert (packed.variant, packed.first_path, packed.path_count) == ("mean_log_delta", 1, 2)
    assert unpack_projection_chunk(packed, expected_inputs=plan.inputs) == chunk


@pytest.mark.parametrize("change", ("first_path", "path_count", "variant", "input_digest"))
def test_chunk_header_and_absolute_range_must_match(
    retained: tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk], change: str
) -> None:
    plan, _, chunk = retained
    packed = pack_projection_chunk(chunk, expected_inputs=plan.inputs)
    changes: dict[str, Any] = {
        "first_path": 0,
        "path_count": 1,
        "variant": "baseline",
        "input_digest": "0" * 64,
    }
    altered = replace(packed, **{change: changes[change]})
    with pytest.raises(ProjectionCodecError):
        unpack_projection_chunk(altered, expected_inputs=plan.inputs)


@pytest.mark.parametrize(
    "change",
    (
        "missing_middle_point",
        "foreign_currency",
        "changed_real",
        "changed_asset",
        "missing_field",
        "unknown_field",
        "duplicate_path",
    ),
)
def test_rehashed_malformed_chunk_does_not_lose_or_repair_retained_points(
    retained: tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk], change: str
) -> None:
    plan, _, chunk = retained
    packed = pack_projection_chunk(chunk, expected_inputs=plan.inputs)
    raw = json.loads(packed.canonical_chunk)
    if change == "missing_middle_point":
        raw["paths"][0]["points"].pop(1)
    elif change == "foreign_currency":
        raw["paths"][0]["reporting_currency"] = "USD"
    elif change == "changed_real":
        raw["paths"][0]["points"][1]["real"] = "99999"
    elif change == "changed_asset":
        raw["paths"][0]["points"][1]["assets"][0]["value"] = "99999"
    elif change == "missing_field":
        raw["paths"][0]["points"][1].pop("wealth_residual")
    elif change == "unknown_field":
        raw["paths"][0]["points"][1]["adjustment"] = "0"
    elif change == "duplicate_path":
        raw["paths"][1] = raw["paths"][0]
    with pytest.raises(ProjectionCodecError):
        unpack_projection_chunk(chunk_bytes(raw, packed), expected_inputs=plan.inputs)


@pytest.mark.parametrize(
    "change",
    (
        "variant_prefix",
        "path_prefix",
        "changed_distribution",
        "changed_histogram",
        "changed_goal",
        "changed_input",
        "float_money",
        "extra_field",
    ),
)
def test_rehashed_result_requires_complete_pinned_financial_content(
    retained: tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk], change: str
) -> None:
    plan, result, _ = retained
    packed = pack_projection_result(result)
    raw = json.loads(packed.canonical_result)
    if change == "variant_prefix":
        raw["variants"] = raw["variants"][:1]
    elif change == "path_prefix":
        raw["variants"][0]["paths"].pop()
    elif change == "changed_distribution":
        raw["variants"][0]["distributions"][1]["nominal_mean"] = "99999"
    elif change == "changed_histogram":
        raw["variants"][0]["nominal_histogram"]["bins"][0]["count"] += 1
    elif change == "changed_goal":
        raw["variants"][0]["goal"]["probability"] = (
            "0" if raw["variants"][0]["goal"]["probability"] != "0" else "1"
        )
    elif change == "changed_input":
        raw["inputs"]["seed"] += 1
    elif change == "float_money":
        raw["variants"][0]["paths"][0]["points"][1]["nominal"] = 1500.5
    elif change == "extra_field":
        raw["variants"][0]["paths"][0]["points"][1]["source_url"] = "https://untrusted.invalid"
    with pytest.raises(ProjectionCodecError):
        unpack_projection_result(result_bytes(raw, packed), expected_inputs=plan.inputs)


def test_wrong_hash_declared_length_and_trailing_bytes_are_rejected(
    retained: tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk],
) -> None:
    plan, result, chunk = retained
    packed = pack_projection_result(result)
    checkpoint = pack_projection_chunk(chunk, expected_inputs=plan.inputs)
    with pytest.raises(ProjectionCodecError):
        replace(packed, content_digest="0" * 64)
    with pytest.raises(ProjectionCodecError):
        replace(packed, byte_length=packed.byte_length + 1)
    with pytest.raises(ProjectionCodecError):
        replace(checkpoint, path_count=True)
    with pytest.raises(ProjectionCodecError):
        replace(checkpoint, path_count=33)
    malformed = packed.canonical_result + b"{}"
    declared = replace(
        packed,
        canonical_result=malformed,
        byte_length=len(malformed),
        content_digest=sha256(malformed).hexdigest(),
    )
    with pytest.raises(ProjectionCodecError):
        unpack_projection_result(declared, expected_inputs=plan.inputs)


def test_rehashed_duplicate_json_fields_are_rejected(
    retained: tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk],
) -> None:
    plan, result, _ = retained
    packed = pack_projection_result(result)
    malformed = packed.canonical_result[:-1] + b',"method_version":"1.0.0"}'
    declared = replace(
        packed,
        canonical_result=malformed,
        byte_length=len(malformed),
        content_digest=sha256(malformed).hexdigest(),
    )
    with pytest.raises(ProjectionCodecError):
        unpack_projection_result(declared, expected_inputs=plan.inputs)


def test_decoding_never_recomputes_sampled_paths(
    retained: tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, result, chunk = retained
    packed = pack_projection_result(result)
    checkpoint = pack_projection_chunk(chunk, expected_inputs=plan.inputs)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("A retained decoder invoked the projection sampler")

    monkeypatch.setattr(kernel, "calculate_projection", forbidden)
    monkeypatch.setattr(kernel, "calculate_projection_chunk", forbidden)
    monkeypatch.setattr(kernel, "_run_path", forbidden)
    assert unpack_projection_result(packed, expected_inputs=plan.inputs) == result
    assert unpack_projection_chunk(checkpoint, expected_inputs=plan.inputs) == chunk


def test_hostile_decimal_context_preserves_all_result_and_chunk_bytes(
    retained: tuple[ProjectionCapturePlan, ProjectionCalculation, ProjectionChunk],
) -> None:
    plan, result, chunk = retained
    packed = pack_projection_result(result)
    checkpoint = pack_projection_chunk(chunk, expected_inputs=plan.inputs)
    context = Context(prec=2, rounding=ROUND_DOWN, Emin=-2, Emax=2)
    context.traps[Inexact] = True
    context.traps[Rounded] = True
    with localcontext(context):
        restored = unpack_projection_result(packed, expected_inputs=plan.inputs)
        assert pack_projection_result(restored) == packed
        restored_chunk = unpack_projection_chunk(checkpoint, expected_inputs=plan.inputs)
        assert pack_projection_chunk(restored_chunk, expected_inputs=plan.inputs) == checkpoint


def test_subquantum_unpaid_funding_flag_survives_exact_round_trip() -> None:
    d = Decimal
    eur = CurrencyCode("EUR")
    version_id = UUID(int=201)
    account = UUID(int=200)
    assumptions = ProjectionAssumptions(
        assets=(
            ProjectionAsset(
                key="cash", annual_mean_log_return=d(0), annual_volatility=d(0), weight=d(1)
            ),
        ),
        correlation=((d(1),),),
        reporting_currency=eur,
        annual_fee=d(".12"),
    )
    version = ProjectionAssumptionVersion(
        account_id=account,
        version_id=version_id,
        content=assumptions,
        content_digest=projection_definition_digest(assumptions),
    )
    schedule = ProjectionDatedSchedule(
        base_monthly=Money(d(0), eur),
        entries=(
            ProjectionDatedEntry(
                key="tiny-withdrawal",
                on=date(2025, 2, 28),
                kind="withdrawal",
                value=Money(d(".000000000000000001"), eur),
            ),
        ),
    )
    selection = ProjectionRunSelection(
        account_id=account,
        assumption_version_id=version_id,
        initial=ProjectionInitialSelection(
            kind="modeled_value",
            modeled_value=Money(d(".000000000000000001"), eur),
            modeled_anchor_date=date(2025, 1, 31),
        ),
        schedule=schedule,
        seed=7,
        months=2,
        paths=1,
        retained_months=(0, 1, 2),
        allocation=(ProjectionAllocation(key="cash", weight=d(1)),),
    )
    plan = ProjectionCapturePlan(selection=selection, assumption_version=version)
    result = kernel.calculate_projection(plan.inputs)
    point = result.variants[0].paths[0].points[-1]
    assert (
        point.funding_failed
        and point.unpaid_positive_below_quantum
        and point.unpaid_withdrawals == 0
    )
    restored = unpack_projection_result(pack_projection_result(result), expected_inputs=plan.inputs)
    assert restored.variants[0].paths[0].first_unpaid_month == 2
    assert restored.variants[0].paths[0].points[-1] == point
