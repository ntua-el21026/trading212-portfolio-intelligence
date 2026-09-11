"""Bounded capture state shared by the fixed canonical alert source families."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session
from trading212_domain import alerts as d
from trading212_domain.enums import QualityState
from trading212_domain.reports import ReportSourceKind
from trading212_domain.sources import SourceLicense
from trading212_domain.values import CurrencyCode

if TYPE_CHECKING:
    from .report_authorization import ReportAuthorization
    from .source_service import PostgresSourceService


class AlertCaptureBound(ValueError):
    """A complete canonical selection exceeds a documented materialization bound."""


class AlertCaptureUnavailable(ValueError):
    def __init__(self, reason: d.AlertReason) -> None:
        super().__init__("Canonical alert evidence is unavailable.")
        self.reason = reason


def bounded[T](rows: list[T], maximum: int) -> list[T]:
    if len(rows) > maximum:
        raise AlertCaptureBound("Alert canonical input exceeds its bound.")
    return rows


class AlertCaptureState:
    def __init__(
        self,
        session: Session,
        authorization: ReportAuthorization,
        version: d.AlertRuleVersion,
        cutoff: datetime,
        window: d.AlertObservationWindow,
        *,
        now: datetime,
        sources: PostgresSourceService,
    ) -> None:
        self.session, self.authorization, self.version = session, authorization, version
        self.predicate, self.cutoff, self.window, self.now = (
            version.definition.predicate,
            cutoff,
            window,
            now,
        )
        self.references: dict[str, d.AlertSourceReference] = {}
        self.sources = sources
        self.bindings: list[d.AlertCanonicalBinding] = []
        self.licenses: dict[str, SourceLicense] = {}
        self.fx_conversions: list[d.AlertMoneyConversion] = []
        self.context = d.AlertResultContext(
            key="context.alert",
            account_id=version.account_id,
            source_cutoff_at=cutoff,
            valuation_at=cutoff,
            method_key=d.ALERT_METHOD,
            method_version=d.ALERT_METHOD_VERSION,
            quality=QualityState.PARTIAL,
        )

    def reference(
        self,
        *,
        kind: ReportSourceKind,
        identifier: UUID,
        digest: str,
        effective_at: datetime,
        known_at: datetime,
        parent_id: UUID | None = None,
        provider_id: UUID | None = None,
        license_id: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        if max(effective_at, known_at) > self.cutoff:
            raise AlertCaptureUnavailable(d.AlertReason.MISSING_INPUT)
        key = f"{kind.value}.{identifier}"
        if key not in self.references and len(self.references) >= d.MAX_ALERT_SOURCE_REFERENCES:
            raise AlertCaptureBound("Alert canonical references exceed their bound.")
        value = d.AlertSourceReference(
            key=key,
            kind=kind,
            subject_id=identifier,
            content_digest=digest,
            effective_at=effective_at,
            first_observed_at=known_at,
            parent_id=parent_id,
            provider_id=provider_id,
            license_version_id=license_id,
            expires_at=expires_at,
        )
        if key in self.references and self.references[key] != value:
            raise AlertCaptureUnavailable(d.AlertReason.AMBIGUOUS_SOURCE)
        self.references[key] = value

    def observation(
        self,
        value: Decimal | int | bool | None,
        *,
        reason: d.AlertReason | None = None,
        basis: Decimal | int | bool | d.AlertRatioBasis | None = None,
        complete: bool = True,
        currency: CurrencyCode | None = None,
        bound: d.AlertBound = d.AlertBound.EXACT,
        positive_below_quantum: bool = False,
    ) -> d.AlertMetricObservation:
        return d.AlertMetricObservation(
            observed=d.AlertObservedMetric(
                metric=self.predicate.metric,
                kind=d.alert_metric_kind(self.predicate.metric),
                value=value,
                currency=currency,
                context_key=self.context.key,
                availability=d.AlertAvailability.UNAVAILABLE
                if value is None
                else (d.AlertAvailability.AVAILABLE if complete else d.AlertAvailability.PARTIAL),
                quality=self.context.quality,
                origin=d.AlertOrigin.DERIVED_DETERMINISTIC,
                reason=reason,
                bound=bound,
                positive_below_quantum=positive_below_quantum,
            ),
            comparison_basis=(basis if basis is not None else value),
            material_complete=complete,
        )

    def unavailable(self, reason: d.AlertReason) -> d.AlertThresholdInput | d.AlertEventBatchInput:
        if self.predicate.metric in {
            d.AlertMetric.REFRESH_FAILED,
            d.AlertMetric.POSITIVE_DIVIDEND,
            d.AlertMetric.ABSOLUTE_EXTERNAL_FLOW_AMOUNT,
            d.AlertMetric.UNCLASSIFIED_ACTIVITY,
            d.AlertMetric.REPORT_TERMINAL,
        }:
            return d.AlertEventBatchInput(events=(), complete=False, reason=reason)
        return d.AlertThresholdInput(
            observation=self.observation(
                None, reason=reason, complete=False, currency=self.predicate.currency
            )
        )

    def finish(
        self,
        payload: d.AlertThresholdInput | d.AlertEventBatchInput,
        execution_intent: d.AlertExecutionIntent,
    ) -> d.AlertEvaluationInput:
        context = replace(self.context, source_reference_keys=tuple(sorted(self.references)))
        return d.AlertEvaluationInput(
            version=self.version,
            scheduled_for=self.cutoff,
            source_cutoff_at=self.cutoff,
            observation_window=self.window,
            payload=payload,
            contexts=(context,),
            execution_intent=execution_intent,
            canonical_bindings=tuple(self.bindings),
            source_references=tuple(self.references[key] for key in sorted(self.references)),
            licenses=tuple(self.licenses[key] for key in sorted(self.licenses)),
            fx_conversions=tuple(self.fx_conversions),
        )
