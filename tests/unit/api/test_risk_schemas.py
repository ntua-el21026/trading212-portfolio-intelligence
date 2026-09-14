"""Strict risk inputs and canonical output projection, including unavailable statistics."""

from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError
from trading212_api.risk_schemas import risk_definition, risk_run
from trading212_api_contracts import risk as wire
from trading212_domain.serialization import to_primitive

from tests.unit.api.risk_factories import ACCOUNT, SNAPSHOT, VERSION, matrix, run, version


def content() -> dict[str, object]:
    return to_primitive(version().content)  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    "field,value",
    [
        ("annual_risk_free", 0.1),
        ("confidence", 0.95),
        ("shrinkage", True),
        ("confidence", ".94"),
        ("annual_risk_free", "-1"),
        ("rolling_window", True),
        ("horizon", 21),
        ("shrinkage", "0.1"),
        ("calendar_id", "https://untrusted.example"),
        ("method_version", "latest"),
        ("name", " "),
        ("extra-private-canary", "private-value-canary"),
    ],
)
def test_strict_definition_rejects_invalid_inputs(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        wire.RiskDefinitionContent.model_validate({**content(), field: value})


def test_monthly_bounds_and_decimal_definition_conversion() -> None:
    model = wire.RiskDefinitionContent.model_validate(
        {**content(), "annual_risk_free": "0.012345678901234567"}
    )
    assert risk_definition(model).annual_risk_free == Decimal("0.012345678901234567")
    for change in ({"horizon": 13}, {"rolling_window": 121}):
        with pytest.raises(ValidationError):
            wire.RiskDefinitionContent.model_validate(
                {**content(), "frequency": "monthly", **change}
            )


def test_run_contains_pins_not_return_arrays_and_rejects_duplicate_mappings() -> None:
    public = run()
    assert public.result is not None
    data = {
        "definition_version_id": str(VERSION),
        "portfolio_snapshot_id": str(SNAPSHOT),
        "historical_input_snapshot_id": str(SNAPSHOT),
        "window": to_primitive(public.result.historical_context.window),
    }
    parsed = wire.CreateRiskRunRequest.model_validate(data)
    command = risk_run(str(ACCOUNT), parsed, key="synthetic-one", correlation="trace-one")
    assert command.account_id == ACCOUNT and command.definition_version_id == VERSION
    asset = {"instrument_id": str(SNAPSHOT), "series_id": str(VERSION)}
    for extra in (
        {"returns": ["0.1"]},
        {"owner_id": str(ACCOUNT)},
        {"assets": [asset, asset]},
        {"assets": [asset] * 33},
    ):
        with pytest.raises(ValidationError):
            wire.CreateRiskRunRequest.model_validate({**data, **extra})


def test_canonical_result_has_no_private_graph_and_preserves_unavailable_reasons() -> None:
    data = to_primitive(run())
    result = wire.RiskRunResponse.model_validate(data)
    assert result.model_dump(mode="json") == data
    assert result.result is not None
    assert result.result.modeled.volatility_annualized.value is None
    assert result.result.modeled.volatility_annualized.reason == "incomplete_universe"
    assert result.result.parametric_tail.quantile == "gaussian_log_wealth"
    assert (
        "source_uses" not in result.model_dump_json()
        and "conversions" not in result.model_dump_json()
    )
    assert (
        wire.RiskMatrixResponse.model_validate(to_primitive(matrix())).matrix
        == result.result.matrix
    )
    mutated = deepcopy(data)
    mutated["result"]["observed"]["volatility_annualized"]["value"] = 0.1
    with pytest.raises(ValidationError):
        wire.RiskRunResponse.model_validate(mutated)
