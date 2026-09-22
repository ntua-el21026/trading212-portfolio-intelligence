"""Authorized exact-period metadata comparison; never decode prices or rates."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from trading212_application import source_fallback as app
from trading212_application.source_providers import FxPair
from trading212_application.sources import SourceServiceError
from trading212_domain import CurrencyCode, QualityState
from trading212_domain.sources import PriceBasis, SourcePeriod, SourceUse
from trading212_security.principals import AuthorizationError, Principal, Scope

from .report_authorization import authorize_report_request
from .source_models import (
    FxObservationModel,
    FxSnapshotModel,
    MarketSourceSeriesModel,
    PriceObservationModel,
    PriceSnapshotModel,
    SourceCalendarModel,
    SourceCalendarSessionModel,
    SourceRetentionWorkModel,
    SourceSnapshotFields,
)
from .source_store import SourceStore

_SCOPES = frozenset({Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ})


class PostgresCompatibleSourceReader(SourceStore):
    """Each candidate and the final comparison reload current durable source authority."""

    def _rights(self, session: Session, row: SourceSnapshotFields) -> None:
        original = self._snapshot_permit(session, row, SourceUse.STORE)
        self._snapshot_permit(session, row, SourceUse.DISPLAY)
        current = self._current_license(session, row.owner_id, row.provider_id)
        pending = session.scalar(
            select(SourceRetentionWorkModel.id)
            .where(
                SourceRetentionWorkModel.owner_id == row.owner_id,
                getattr(SourceRetentionWorkModel, self._snapshot_reference(row)) == row.id,
            )
            .limit(1)
        )
        if (
            current is None
            or pending is not None
            or original.retention_days is None
            or current.retention_days is None
        ):
            raise app.SourceFallbackError(app.SourceFallbackReason.SOURCE_UNAVAILABLE)
        # Current rights may shorten the effective copy deadline. Public evidence
        # still records the original physical expiry, without renewing its clock.
        deadline = min(
            row.expires_at,
            row.first_observed_at
            + timedelta(days=min(original.retention_days, current.retention_days)),
        )
        if deadline <= self._now():
            raise app.SourceFallbackError(app.SourceFallbackReason.SOURCE_UNAVAILABLE)

    async def inspect_price(
        self,
        principal: Principal,
        plan: app.PriceFallbackPlan,
        candidate: app.RetainedSourceCandidate,
    ) -> app.FallbackSourceFacts:
        if type(plan) is not app.PriceFallbackPlan:
            raise ValueError("An exact price plan is required.")
        return await self._inspect(principal, plan, candidate)

    async def inspect_fx(
        self, principal: Principal, plan: app.FxFallbackPlan, candidate: app.RetainedSourceCandidate
    ) -> app.FallbackSourceFacts:
        if type(plan) is not app.FxFallbackPlan:
            raise ValueError("An exact FX plan is required.")
        return await self._inspect(principal, plan, candidate)

    async def _inspect(
        self,
        principal: Principal,
        plan: app.SourceFallbackPlan,
        candidate: app.RetainedSourceCandidate,
    ) -> app.FallbackSourceFacts:
        def execute() -> app.FallbackSourceFacts:
            try:
                with self._sessions() as session, session.begin():
                    auth = authorize_report_request(
                        session,
                        principal,
                        account_id=plan.account_id,
                        required_scopes=_SCOPES,
                        now=self._now(),
                    )
                    if auth.owner_id != plan.owner_id:
                        raise AuthorizationError("access denied")
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                        {"key": f"sources:{auth.owner_id}"},
                    )
                    model = (
                        PriceSnapshotModel
                        if isinstance(plan, app.PriceFallbackPlan)
                        else FxSnapshotModel
                    )
                    row = self._owned(session, auth.owner_id, model, candidate.snapshot_id)
                    if not isinstance(row, (PriceSnapshotModel, FxSnapshotModel)):
                        raise app.SourceFallbackError(app.SourceFallbackReason.SOURCE_UNAVAILABLE)
                    self._rights(session, row)
                    if row.content_digest != candidate.content_digest:
                        raise app.SourceFallbackError(app.SourceFallbackReason.CONTENT_MISMATCH)
                    result = self._facts(session, row)
                    self._rights(session, row)
                    auth.check(session, now=self._now())
                    return result
            except AuthorizationError:
                raise app.SourceFallbackError(app.SourceFallbackReason.ACCESS_DENIED) from None
            except (SourceServiceError, SQLAlchemyError, ValueError):
                raise app.SourceFallbackError(app.SourceFallbackReason.SOURCE_UNAVAILABLE) from None

        return await asyncio.to_thread(execute)

    def _facts(
        self, session: Session, row: PriceSnapshotModel | FxSnapshotModel
    ) -> app.FallbackSourceFacts:
        series = None
        if isinstance(row, PriceSnapshotModel):
            series = self._owned(session, row.owner_id, MarketSourceSeriesModel, row.series_id)
            calendar_id = series.calendar_id
        else:
            calendar_id = row.calendar_id
        calendar = self._owned(session, row.owner_id, SourceCalendarModel, calendar_id)
        if not calendar.period_start <= row.period_start <= row.period_end <= calendar.period_end:
            raise app.SourceFallbackError(app.SourceFallbackReason.INCOMPATIBLE_CALENDAR)
        expected_sessions = int(
            session.scalar(
                select(func.count())
                .select_from(SourceCalendarSessionModel)
                .where(
                    SourceCalendarSessionModel.owner_id == row.owner_id,
                    SourceCalendarSessionModel.calendar_id == calendar_id,
                    SourceCalendarSessionModel.session_date.between(
                        row.period_start, row.period_end
                    ),
                )
            )
            or 0
        )
        pairs: tuple[FxPair, ...] = ()
        observation = (
            PriceObservationModel if isinstance(row, PriceSnapshotModel) else FxObservationModel
        )
        # Only counters, dates and pair identity are selected; monetary columns are
        # not read. No differing-period subset is silently substituted.
        counts = session.execute(
            select(
                func.count(),
                func.count().filter(observation.state == "available"),
                func.max(observation.effective_at),
                func.count().filter(
                    ~observation.session_date.between(row.period_start, row.period_end)
                ),
            ).where(observation.owner_id == row.owner_id, observation.snapshot_id == row.id)
        ).one()
        if isinstance(row, FxSnapshotModel):
            found = session.execute(
                select(FxObservationModel.base, FxObservationModel.quote)
                .where(
                    FxObservationModel.owner_id == row.owner_id,
                    FxObservationModel.snapshot_id == row.id,
                )
                .group_by(FxObservationModel.base, FxObservationModel.quote)
                .order_by(FxObservationModel.base, FxObservationModel.quote)
                .limit(33)
            ).all()
            if len(found) > 32:
                raise app.SourceFallbackError(app.SourceFallbackReason.INCOMPATIBLE_PAIRS)
            pairs = tuple(
                FxPair(base=CurrencyCode(base), quote=CurrencyCode(quote)) for base, quote in found
            )
        expected = expected_sessions * (len(pairs) if isinstance(row, FxSnapshotModel) else 1)
        # A complete retained source can contain explicit missing observations or
        # coverage gaps. Available rows, original expected count and calendar must
        # agree; absent or purged financial rows cannot claim the old coverage.
        if (
            counts[3]
            or counts[0] > expected
            or counts[1] != row.available_count
            or expected != row.expected_count
        ):
            raise app.SourceFallbackError(app.SourceFallbackReason.INSUFFICIENT_COVERAGE)
        if series is not None and series.instrument_id is None:
            raise app.SourceFallbackError(app.SourceFallbackReason.INCOMPATIBLE_SUBJECT)
        return app.FallbackSourceFacts(
            family="price" if series is not None else "fx",
            snapshot_id=row.id,
            content_digest=row.content_digest,
            provider_id=row.provider_id,
            license_version_id=row.license_version_id,
            calendar_id=calendar_id,
            calendar_version=calendar.version,
            period=SourcePeriod(start=row.period_start, end=row.period_end),
            first_known_at=row.first_observed_at,
            original_expires_at=row.expires_at,
            latest_observation_at=counts[2],
            expected_count=expected,
            available_count=counts[1],
            quality=QualityState(row.quality),
            synthetic=row.synthetic,
            instrument_id=None if series is None else series.instrument_id,
            currency=None if series is None else CurrencyCode(series.currency),
            basis=None if series is None else PriceBasis(series.basis),
            pairs=pairs,
        )
