"""Exact MCP run selection conversion; source identities never confer authority."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from uuid import UUID

from trading212_api_contracts import projection_inputs as wire
from trading212_application import projection as app
from trading212_application import projection_capture as capture
from trading212_domain import projection as domain
from trading212_domain.values import CurrencyCode, Money


def _money(value: wire.ProjectionMoney) -> Money:
    return Money(Decimal(value.amount), CurrencyCode(value.currency))


def projection_command(
    account_id: str,
    value: wire.CreateProjectionRunRequest,
    *,
    idempotency_key: str,
    correlation: str,
) -> app.CreateProjectionRun:
    initial, sensitivity = value.initial_basis, value.sensitivity
    selection = capture.ProjectionRunSelection(
        account_id=UUID(account_id),
        assumption_version_id=UUID(value.assumption_version_id),
        goal_version_id=None if value.goal_version_id is None else UUID(value.goal_version_id),
        initial=capture.ProjectionInitialSelection(
            kind=initial.kind,
            snapshot_id=None if initial.snapshot_id is None else UUID(initial.snapshot_id),
            modeled_value=None if initial.modeled_value is None else _money(initial.modeled_value),
            modeled_anchor_date=initial.modeled_anchor_date,
        ),
        schedule=capture.ProjectionDatedSchedule(
            base_monthly=_money(value.schedule.base_monthly),
            annual_growth=Decimal(value.schedule.annual_growth),
            paused_dates=tuple(value.schedule.paused_dates),
            entries=tuple(
                capture.ProjectionDatedEntry(
                    key=item.key, on=item.on, kind=item.kind, value=_money(item.value)
                )
                for item in value.schedule.entries
            ),
        ),
        seed=value.seed,
        months=value.months,
        paths=value.paths,
        retained_months=tuple(value.retained_months),
        allocation=tuple(
            domain.ProjectionAllocation(key=item.key, weight=Decimal(item.weight))
            for item in value.allocation
        ),
        sensitivity=None
        if sensitivity is None
        else domain.ProjectionSensitivity(
            contribution_delta=_money(sensitivity.contribution_delta),
            annual_mean_log_delta=Decimal(sensitivity.annual_mean_log_delta),
        ),
    )
    return app.CreateProjectionRun(
        selection=selection,
        idempotency_key=idempotency_key,
        correlation_id=correlation
        if len(correlation) <= 120
        else "sha256:" + hashlib.sha256(correlation.encode()).hexdigest(),
    )
