"""Independent section 18 registry cases, including the three ordered P208 pins.

This is an authored acceptance oracle, not a projection of production registration.
Synthetic identifiers below are argument fixtures, not retained financial evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACCOUNT = "d778f930-9d2e-4f47-b24f-5b1fa99c6eee"
SNAPSHOT = "5dd1049e-7433-43f4-bf5b-3a73c24c0568"
PORTFOLIO = "aef0bdf3-3613-4cfe-b15f-bc1f8b9c4119"
TARGET = "19a8b590-9c18-4c43-8dce-d622cb6ae033"
RESOURCE = "b7e267ab-9f80-4cda-8f5e-e5c28a7f72b9"

P = "portfolio:read"
A = "activity:read"
T = "targets:read"
N = "analytics:read"
PLAN_WRITE = "plans:write"
REPORT_READ = "reports:read"
REPORT_WRITE = "reports:write"
ALERT_READ = "alerts:read"

_ACCOUNT: dict[str, Any] = {"account_id": ACCOUNT}
_LEGACY_WINDOW: dict[str, Any] = {
    **_ACCOUNT,
    "start_date": "2026-01-01",
    "end_date": "2026-08-31",
}
_WINDOW: dict[str, Any] = {
    **_ACCOUNT,
    "start_date": "2026-09-01",
    "end_date": "2026-09-07",
    "source_cutoff_at": "2026-09-07T12:00:00Z",
    "reporting_currency": "EUR",
}
_TARGET: dict[str, Any] = {
    **_ACCOUNT,
    "snapshot_id": SNAPSHOT,
    "virtual_portfolio_id": PORTFOLIO,
    "target_version_id": TARGET,
    "reporting_currency": "EUR",
}


@dataclass(frozen=True)
class RegistryCase:
    name: str
    scopes: tuple[str, ...]
    arguments: dict[str, Any]
    optional: tuple[str, ...] = ()
    service_method: str | None = None
    command: bool = False

    @property
    def required(self) -> set[str]:
        return set(self.arguments)

    @property
    def legacy(self) -> bool:
        return self.service_method is None


# Order follows the owner catalogue. Discovery may group commands with their family.
CASES = (
    RegistryCase("get_account_summary", (P,), _ACCOUNT),
    RegistryCase("get_portfolio_snapshot", (P,), _ACCOUNT, ("snapshot_id",)),
    RegistryCase(
        "list_positions",
        (P,),
        _ACCOUNT,
        ("cursor", "limit", "sort", "search"),
    ),
    RegistryCase(
        "list_recent_transactions",
        (P, A),
        _LEGACY_WINDOW,
        ("type_filter", "cursor", "limit"),
    ),
    RegistryCase("get_dividend_summary", (P, A), _LEGACY_WINDOW, ("recent_limit",)),
    RegistryCase("get_direct_allocation", (P,), _ACCOUNT, ("top_n",)),
    RegistryCase(
        "compare_portfolio_snapshots",
        (P,),
        {
            **_ACCOUNT,
            "start_snapshot_id": "snapshot-2026-07-31",
            "end_snapshot_id": "snapshot-2026-08-31",
        },
    ),
    RegistryCase("get_reconciliation_status", (P,), _ACCOUNT, ("issue_limit",)),
    RegistryCase("get_data_quality_summary", (P, A), _ACCOUNT),
    RegistryCase(
        "list_virtual_pies",
        (P, T),
        _ACCOUNT,
        ("cursor", "limit", "state", "search", "sort"),
        "list_virtual_portfolios",
    ),
    RegistryCase(
        "get_virtual_pie",
        (P, T),
        {**_ACCOUNT, "virtual_portfolio_id": PORTFOLIO},
        ("target_version_id", "parent_node_id", "cursor", "limit"),
        "get_virtual_portfolio_targets",
    ),
    RegistryCase(
        "get_actual_vs_target",
        (P, T, N),
        _TARGET,
        ("node_id", "cursor", "limit", "xray_run_id"),
        "get_actual_vs_target",
    ),
    RegistryCase(
        "get_drift_analysis",
        (P, T, N),
        _TARGET,
        ("basis", "top_n", "xray_run_id"),
        "get_drift_analysis",
    ),
    RegistryCase(
        "get_contribution_plan",
        (P, N),
        {**_ACCOUNT, "plan_id": RESOURCE},
        ("plan_revision_id", "cursor", "limit"),
        "get_contribution_plan",
    ),
    RegistryCase(
        "get_performance_summary",
        (P, N),
        _WINDOW,
        ("method", "frequency"),
        "get_performance_summary",
    ),
    RegistryCase(
        "get_benchmark_comparison",
        (P, N),
        {**_WINDOW, "benchmark_version_id": RESOURCE},
        ("frequency",),
        "get_benchmark_comparison",
    ),
    RegistryCase(
        "get_dividend_intelligence",
        (P, A, N),
        _WINDOW,
        ("top_n",),
        "get_dividend_intelligence",
    ),
    RegistryCase(
        "get_attribution_summary",
        (P, N, T),
        _WINDOW,
        ("grouping", "target_version_id", "top_n"),
        "get_attribution_summary",
    ),
    RegistryCase(
        "get_effective_exposure",
        (P, N),
        {
            **_ACCOUNT,
            "snapshot_id": SNAPSHOT,
            "source_cutoff_at": "2026-09-07T12:00:00Z",
            "reporting_currency": "EUR",
        },
        ("dimension", "cursor", "limit"),
        "get_effective_exposure",
    ),
    RegistryCase(
        "get_etf_overlap",
        (P, N),
        {
            **_ACCOUNT,
            "snapshot_id": SNAPSHOT,
            "source_cutoff_at": "2026-09-07T12:00:00Z",
            "left_fund_id": PORTFOLIO,
            "right_fund_id": RESOURCE,
        },
        ("top_n",),
        "get_etf_overlap",
    ),
    RegistryCase(
        "get_report_status",
        (P, REPORT_READ),
        {**_ACCOUNT, "report_job_id": RESOURCE},
        (),
        "get_report_status",
    ),
    RegistryCase(
        "list_reports",
        (P, REPORT_READ),
        _ACCOUNT,
        ("cursor", "limit", "state", "report_type", "sort"),
        "list_reports",
    ),
    RegistryCase(
        "get_alert_summary",
        (P, ALERT_READ),
        {key: value for key, value in _WINDOW.items() if key != "reporting_currency"},
        ("state", "severity", "cursor", "limit"),
        "get_summary",
    ),
    RegistryCase(
        "create_contribution_plan",
        (P, T, N, PLAN_WRITE),
        {
            **{key: value for key, value in _TARGET.items() if key != "reporting_currency"},
            "idempotency_key": "p209:plan:one",
            "contribution": {"amount": "10", "currency": "EUR"},
            "mode": "cash_only",
        },
        (
            "restricted_group_ids",
            "eligible_holding_ids",
            "excluded_holding_ids",
            "listing_preferences",
            "allocation_constraints",
            "cash_reserve",
            "monetary_quantum",
            "coverage_policy",
        ),
        "create_contribution_plan",
        True,
    ),
    RegistryCase(
        "generate_portfolio_report",
        (P, N, REPORT_WRITE, A, T),
        {
            **_WINDOW,
            "snapshot_id": SNAPSHOT,
            "idempotency_key": "p209:report:one",
            "report_type": "portfolio_summary",
            "format": "json",
            "sections": ["overview", "allocation", "quality"],
        },
        (
            "target_version_id",
            "plan_revision_id",
            "benchmark_version_id",
            "constituent_snapshot_id",
            "xray_run_id",
        ),
        "generate_report",
        True,
    ),
)
LEGACY_CASES = CASES[:9]
NEW_CASES = CASES[9:]
