"""Closed immutable owner assumptions for the deterministic stress method."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Literal
from uuid import UUID

from .errors import fail_validation
from .sources import source_key
from .values import CurrencyCode, exact_decimal, require_bounded_text

SCENARIO_METHOD = "stress_v1"
SCENARIO_VERSION = "1.0.0"
SCENARIO_NUMERICAL_PROFILE = "premium_decimal96_q18_v1"
MAX_SCENARIO_BYTES = 33_554_432
MAX_SCENARIO_COMPONENTS = 10_000
MAX_SCENARIO_RULES = 128
MAX_SCENARIO_SENSITIVITY_ROWS = 100_000
MAX_SCENARIO_LICENSES = 8192


class ScenarioReason(StrEnum):
    MISSING_VALUE = "missing_value"
    MISSING_IDENTITY = "missing_identity"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    MISSING_CLASSIFICATION = "missing_classification"
    AMBIGUOUS_CLASSIFICATION = "ambiguous_classification"
    INCOMPATIBLE_TAXONOMY = "incompatible_taxonomy"
    MISSING_ECONOMIC_CURRENCY = "missing_economic_currency"
    UNSUPPORTED_ECONOMIC_CURRENCY = "unsupported_economic_currency"
    UNCERTAIN_EXCLUSION = "uncertain_exclusion"
    UNCERTAIN_PRICE_PRIORITY = "uncertain_price_priority"
    MISSING_SENSITIVITY = "missing_sensitivity"
    AMBIGUOUS_SENSITIVITY = "ambiguous_sensitivity"
    UNSUPPORTED_SENSITIVITY = "unsupported_sensitivity"
    INCOMPATIBLE_SENSITIVITY_CURRENCY = "incompatible_sensitivity_currency"
    UNKNOWN_DRIVER_EQUIVALENCE = "unknown_driver_equivalence"
    MISSING_REPLAY_MAPPING = "missing_replay_mapping"
    AMBIGUOUS_REPLAY_MAPPING = "ambiguous_replay_mapping"
    MISSING_REPLAY_SOURCE = "missing_replay_source"
    FX_DECOMPOSITION_UNAVAILABLE = "fx_decomposition_unavailable"
    HISTORICAL_HOLDINGS_UNAVAILABLE = "historical_holdings_unavailable"
    INCOMPATIBLE_BASIS = "incompatible_basis"
    UNCERTAIN_MONEY = "uncertain_money"
    ZERO_DENOMINATOR = "zero_denominator"


class ScenarioAssumption(StrEnum):
    OWNER_DEFINED_SHOCKS = "owner_defined_shocks"
    ADDITIONAL_PRICE_COMPONENT = "additional_price_component"
    FIRST_ORDER_FORMULA = "first_order_formula"
    COMPOUNDED_FORMULA = "compounded_formula"
    CANONICAL_TERMINAL_BASIS = "canonical_terminal_basis"
    COUNTERFACTUAL_REPLAY = "counterfactual_replay"
    FIXED_CASH_BALANCE_REPLAY = "fixed_cash_balance_replay"
    RETROSPECTIVE_MARKET_KNOWLEDGE = "retrospective_market_knowledge"
    KNOWN_ONLY_SUBTOTALS = "known_only_subtotals"
    NO_LISTING_CURRENCY_INFERENCE = "no_listing_currency_inference"


class ScenarioRecord:
    __slots__ = ()

    def __post_init__(self) -> None:
        from .scenario_validation import validate_scenario_record

        validate_scenario_record(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioInstrumentSelector(ScenarioRecord):
    instrument_id: UUID
    kind: Literal["instrument"] = "instrument"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioEntitySelector(ScenarioRecord):
    entity_id: UUID
    kind: Literal["entity"] = "entity"


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSectorSelector(ScenarioRecord):
    taxonomy_id: UUID
    taxonomy_version: str
    bucket_key: str
    kind: Literal["sector"] = "sector"

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        source_key(self.taxonomy_version, "taxonomy_version")
        source_key(self.bucket_key, "bucket_key")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioRegionSelector(ScenarioRecord):
    taxonomy_id: UUID
    taxonomy_version: str
    bucket_key: str
    kind: Literal["region"] = "region"

    def __post_init__(self) -> None:
        ScenarioRecord.__post_init__(self)
        source_key(self.taxonomy_version, "taxonomy_version")
        source_key(self.bucket_key, "bucket_key")


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioCurrencySelector(ScenarioRecord):
    currency: CurrencyCode
    kind: Literal["economic_currency"] = "economic_currency"


type ScenarioPriceSelector = (
    ScenarioInstrumentSelector
    | ScenarioEntitySelector
    | ScenarioSectorSelector
    | ScenarioRegionSelector
)
type ScenarioComponentSelector = ScenarioPriceSelector | ScenarioCurrencySelector


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioSensitivityVersionPin(ScenarioRecord):
    version_id: UUID
    content_digest: str
    driver_id: UUID
    driver_definition_version_id: UUID


def _size(value: Decimal, low: str, high: str) -> Decimal:
    parsed = exact_decimal(value, field="size")
    if not Decimal(low) <= parsed <= Decimal(high):
        fail_validation("Scenario shock is outside its declared range.", field="size")
    return parsed


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioPriceShock(ScenarioRecord):
    selector: ScenarioPriceSelector
    size: Decimal
    kind: Literal["price"] = "price"

    def __post_init__(self) -> None:
        object.__setattr__(self, "size", _size(self.size, "-1", "5"))
        ScenarioRecord.__post_init__(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioFxShock(ScenarioRecord):
    selector: ScenarioCurrencySelector
    size: Decimal
    kind: Literal["fx"] = "fx"

    def __post_init__(self) -> None:
        object.__setattr__(self, "size", _size(self.size, "-1", "5"))
        ScenarioRecord.__post_init__(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioRateShock(ScenarioRecord):
    source: ScenarioSensitivityVersionPin
    size: Decimal
    kind: Literal["rate"] = "rate"

    def __post_init__(self) -> None:
        object.__setattr__(self, "size", _size(self.size, "-1", "1"))
        ScenarioRecord.__post_init__(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioFactorShock(ScenarioRecord):
    source: ScenarioSensitivityVersionPin
    size: Decimal
    kind: Literal["factor"] = "factor"

    def __post_init__(self) -> None:
        object.__setattr__(self, "size", _size(self.size, "-1", "1"))
        ScenarioRecord.__post_init__(self)


type ScenarioShock = ScenarioPriceShock | ScenarioFxShock | ScenarioRateShock | ScenarioFactorShock


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioExclusion(ScenarioRecord):
    selector: ScenarioComponentSelector


def scenario_rule_key(value: ScenarioShock) -> str:
    from .scenario_serialization import scenario_record_bytes

    if type(value) not in (
        ScenarioPriceShock,
        ScenarioFxShock,
        ScenarioRateShock,
        ScenarioFactorShock,
    ):
        fail_validation("A fixed scenario shock is required.", field="shock")
    return (
        "shock:" + sha256(b"t212pi.scenario.rule.v1\0" + scenario_record_bytes(value)).hexdigest()
    )


def scenario_exclusion_key(value: ScenarioExclusion) -> str:
    from .scenario_serialization import scenario_record_bytes

    if type(value) is not ScenarioExclusion:
        fail_validation("A fixed scenario exclusion is required.", field="exclusion")
    return (
        "exclusion:"
        + sha256(b"t212pi.scenario.exclusion.v1\0" + scenario_record_bytes(value)).hexdigest()
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ScenarioVersionContent(ScenarioRecord):
    name: str
    description: str
    mode: Literal["first_order", "compounded"]
    shocks: tuple[ScenarioShock, ...] = ()
    exclusions: tuple[ScenarioExclusion, ...] = ()
    method_version: Literal["1.0.0"] = "1.0.0"

    def __post_init__(self) -> None:
        if (
            type(self.shocks) is not tuple
            or type(self.exclusions) is not tuple
            or (len(self.shocks) > MAX_SCENARIO_RULES or len(self.exclusions) > MAX_SCENARIO_RULES)
        ):
            fail_validation("Scenario rules exceed their finite bounds.", field="shocks")
        ScenarioRecord.__post_init__(self)
        require_bounded_text(self.name, field="name", maximum=120)
        require_bounded_text(self.description, field="description", maximum=1024, allow_empty=True)
        identities = [
            ("selector", item.selector)
            if isinstance(item, (ScenarioPriceShock, ScenarioFxShock))
            else ("driver", item.source.driver_id)
            for item in self.shocks
        ]
        if len(set(identities)) != len(identities) or len(set(self.exclusions)) != len(
            self.exclusions
        ):
            fail_validation("Scenario rules must have distinct selectors/drivers.", field="shocks")
        object.__setattr__(self, "shocks", tuple(sorted(self.shocks, key=scenario_rule_key)))
        object.__setattr__(
            self, "exclusions", tuple(sorted(self.exclusions, key=scenario_exclusion_key))
        )
