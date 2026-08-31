"""Fixed metadata for the fourteen mandatory synthetic Phase 1 scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from trading212_domain import QualityState

ScenarioLayer = Literal["analytics", "ingestion_quality", "authorization_boundary"]


@dataclass(frozen=True, slots=True)
class Phase1Scenario:
    scenario_id: str
    name: str
    layer: ScenarioLayer
    expected_quality: QualityState | None
    authoritative_expectation: str


PHASE_1_SCENARIOS = (
    Phase1Scenario(
        "empty_eur_account",
        "Empty EUR account",
        "analytics",
        QualityState.FRESH,
        "Known cash, invested, and portfolio totals are exactly zero; allocation is unavailable.",
    ),
    Phase1Scenario(
        "single_currency_buy_and_hold",
        "Simple single-currency buy-and-hold",
        "analytics",
        QualityState.FRESH,
        "Observed value is aggregated exactly without FX and no-flow gain is reproducible.",
    ),
    Phase1Scenario(
        "fractional_multi_position",
        "Fractional multi-position portfolio",
        "analytics",
        QualityState.FRESH,
        "Fractional quantities retain Decimal precision and direct weights expose residual.",
    ),
    Phase1Scenario(
        "multi_currency_with_fx",
        "Multi-currency positions with FX",
        "analytics",
        QualityState.FRESH,
        "Reporting values use explicit directional on-or-before-cutoff FX observations.",
    ),
    Phase1Scenario(
        "external_and_internal_flows",
        "Deposits/withdrawals plus buys/sells",
        "analytics",
        QualityState.FRESH,
        "Only deposits and withdrawals change net external contributions.",
    ),
    Phase1Scenario(
        "income_fees_withholding",
        "Dividends, fees, and withholding",
        "analytics",
        QualityState.FRESH,
        "Income and negative charges remain separate from external contributions.",
    ),
    Phase1Scenario(
        "partial_history",
        "Partial historical coverage",
        "analytics",
        QualityState.PARTIAL,
        "Net contributions, reconstructed cost, and returns are unavailable rather than zero.",
    ),
    Phase1Scenario(
        "duplicate_and_updated_events",
        "Duplicate and updated provider events",
        "analytics",
        QualityState.FRESH,
        "Identical events and status-only updates produce one economic ledger event.",
    ),
    Phase1Scenario(
        "unmapped_instrument",
        "Unmapped instrument",
        "analytics",
        QualityState.PARTIAL,
        "Observed value remains in totals while classification remains explicitly partial.",
    ),
    Phase1Scenario(
        "unsupported_unknown_activity",
        "Unsupported/unknown activity",
        "analytics",
        QualityState.PARTIAL,
        "Unknown activity is retained and blocks unsupported accounting claims.",
    ),
    Phase1Scenario(
        "reconciliation_mismatch",
        "Reconciliation mismatch",
        "analytics",
        QualityState.UNRECONCILED,
        "Residual beyond tolerance creates a visible discrepancy and unreconciled state.",
    ),
    Phase1Scenario(
        "stale_sources",
        "Stale sources",
        "analytics",
        QualityState.STALE,
        "Structurally valid stale values retain timestamps and cannot become fresh downstream.",
    ),
    Phase1Scenario(
        "provider_failure_or_schema_drift",
        "Provider rate limit/transient outage/schema drift",
        "ingestion_quality",
        QualityState.PARTIAL,
        (
            "Missing capability output degrades only dependent analytics; "
            "schema-invalid data is not used."
        ),
    ),
    Phase1Scenario(
        "cross_owner_attempt",
        "Cross-owner authorization attempt",
        "authorization_boundary",
        None,
        (
            "Authorization rejects the request before analytics; "
            "analytics also rejects mixed accounts."
        ),
    ),
)

PHASE_1_SCENARIOS_BY_ID = MappingProxyType(
    {scenario.scenario_id: scenario for scenario in PHASE_1_SCENARIOS}
)


def get_phase1_scenario(scenario_id: str) -> Phase1Scenario:
    try:
        return PHASE_1_SCENARIOS_BY_ID[scenario_id]
    except KeyError as exc:
        raise KeyError(f"unknown Phase 1 scenario: {scenario_id}") from exc
