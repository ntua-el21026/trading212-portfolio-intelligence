"""Fixed internal owner-authorized historical policy and evidence registration ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from trading212_domain.historical import (
    CalendarRef,
    HistoricalAccountingPolicy,
    HistoricalActivityCoverage,
    HistoricalClassificationEvidence,
    HistoricalOpening,
    HistoricalValuationAnchor,
    InceptionHistoricalOpening,
    ObservedHistoricalOpening,
    UnavailableHistoricalOpening,
)
from trading212_domain.sources import SourceSelectionPolicy, source_id, source_key, source_tuple
from trading212_domain.values import require_utc
from trading212_security.principals import Principal


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalPolicyRegistration:
    id: str
    key: str
    effective_at: datetime
    accounting_policy: HistoricalAccountingPolicy
    source_policy: SourceSelectionPolicy
    reporting_calendar_ref: CalendarRef
    price_series_ids: tuple[str, ...] = ()
    action_series_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        source_id(self.id)
        source_key(self.key)
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        for field, kind in (
            ("accounting_policy", HistoricalAccountingPolicy),
            ("source_policy", SourceSelectionPolicy),
            ("reporting_calendar_ref", CalendarRef),
        ):
            if not isinstance(getattr(self, field), kind):
                raise ValueError("A typed historical registration field is required.")
        for field in ("price_series_ids", "action_series_ids"):
            values = getattr(self, field)
            source_tuple(values, str, field, 256)
            if len(values) != len(set(values)):
                raise ValueError("Historical catalog references must be unique.")
            for value in values:
                source_id(value, field)


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalActivityCoverageRegistration:
    id: str
    ingestion_run_id: str
    capability: Literal["historical_orders", "historical_transactions", "historical_dividends"]
    start_at: datetime
    end_at: datetime
    coverage_complete: bool

    def __post_init__(self) -> None:
        HistoricalActivityCoverage(
            id=self.id,
            ingestion_run_id=self.ingestion_run_id,
            capability=self.capability,
            start_at=self.start_at,
            end_at=self.end_at,
            first_observed_at=self.end_at,
            coverage_complete=self.coverage_complete,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalEvidenceRegistration:
    id: str
    key: str
    opening: HistoricalOpening | None = None
    valuation_anchors: tuple[HistoricalValuationAnchor, ...] = ()
    classifications: tuple[HistoricalClassificationEvidence, ...] = ()
    activity_coverage: tuple[HistoricalActivityCoverageRegistration, ...] = ()

    def __post_init__(self) -> None:
        source_id(self.id)
        source_key(self.key)
        if self.opening is not None and not isinstance(
            self.opening,
            (ObservedHistoricalOpening, InceptionHistoricalOpening, UnavailableHistoricalOpening),
        ):
            raise ValueError("Typed historical opening evidence is required.")
        source_tuple(self.valuation_anchors, HistoricalValuationAnchor, "valuation_anchors", 10000)
        source_tuple(self.classifications, HistoricalClassificationEvidence, "classifications", 256)
        source_tuple(
            self.activity_coverage,
            HistoricalActivityCoverageRegistration,
            "activity_coverage",
            10000,
        )
        if (
            self.opening is None
            and not self.valuation_anchors
            and not self.classifications
            and not self.activity_coverage
        ):
            raise ValueError("Historical evidence registration must contain evidence.")
        for values in (self.valuation_anchors, self.classifications, self.activity_coverage):
            if len({x.id for x in values}) != len(values):
                raise ValueError("Historical evidence identities must be unique.")


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalPolicyView:
    registration: HistoricalPolicyRegistration
    first_observed_at: datetime
    content_digest: str


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoricalEvidenceView:
    registration: HistoricalEvidenceRegistration
    first_observed_at: datetime
    content_digest: str


class HistoricalEvidenceStore(Protocol):
    async def register_historical_policy(
        self,
        principal: Principal,
        account_id: str,
        registration: HistoricalPolicyRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HistoricalPolicyView: ...

    async def register_historical_evidence(
        self,
        principal: Principal,
        account_id: str,
        evidence: HistoricalEvidenceRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HistoricalEvidenceView: ...
