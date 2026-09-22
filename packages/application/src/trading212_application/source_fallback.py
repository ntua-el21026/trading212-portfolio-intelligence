"""Explicit ordered canonical price/FX fallback; no blending or generic dispatch."""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Context, Decimal, localcontext
from enum import StrEnum
from typing import Literal, Protocol, cast
from uuid import UUID

from trading212_domain import CurrencyCode, QualityState, require_utc
from trading212_domain.sources import PriceBasis, SourcePeriod
from trading212_security.principals import Principal

from .source_providers import FxPair


class SourceFallbackReason(StrEnum):
    DISABLED = "disabled"
    SOURCE_UNAVAILABLE = "source_unavailable"
    CONTENT_MISMATCH = "content_mismatch"
    INCOMPATIBLE_SUBJECT = "incompatible_subject"
    INCOMPATIBLE_CURRENCY = "incompatible_currency"
    INCOMPATIBLE_CALENDAR = "incompatible_calendar"
    INCOMPATIBLE_BASIS = "incompatible_basis"
    INCOMPATIBLE_PERIOD = "incompatible_period"
    INCOMPATIBLE_PAIRS = "incompatible_pairs"
    SYNTHETIC_MISMATCH = "synthetic_mismatch"
    SOURCE_AFTER_CUTOFF = "source_after_cutoff"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    QUALITY_NOT_ACCEPTED = "quality_not_accepted"
    ACQUISITION_UNAVAILABLE = "acquisition_unavailable"
    ACCESS_DENIED = "access_denied"


class SourceFallbackError(Exception):
    def __init__(self, reason: SourceFallbackReason) -> None:
        self.reason = reason
        super().__init__("The explicit source fallback is unavailable.")


@dataclass(frozen=True, slots=True, kw_only=True)
class RetainedSourceCandidate:
    snapshot_id: UUID
    content_digest: str

    def __post_init__(self) -> None:
        if (
            type(self.snapshot_id) is not UUID
            or type(self.content_digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.content_digest) is None
        ):
            raise ValueError("An exact retained source pin is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class FallbackAcquisitionPin:
    request_id: UUID
    mapping_version_id: UUID

    def __post_init__(self) -> None:
        if type(self.request_id) is not UUID or type(self.mapping_version_id) is not UUID:
            raise ValueError("An immutable original acquisition request group is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class _Plan:
    owner_id: UUID
    account_id: UUID
    calendar_id: UUID
    calendar_version: str
    period: SourcePeriod
    source_cutoff_at: datetime
    candidates: tuple[RetainedSourceCandidate, ...]
    acquisition: FallbackAcquisitionPin | None = None
    enabled: bool = False
    synthetic: bool = False
    minimum_coverage: Decimal = Decimal("1")
    accepted_qualities: tuple[QualityState, ...] = (QualityState.FRESH,)

    def __post_init__(self) -> None:
        if (
            any(type(x) is not UUID for x in (self.owner_id, self.account_id, self.calendar_id))
            or type(self.calendar_version) is not str
            or not 1 <= len(self.calendar_version) <= 120
            or not self.calendar_version.isascii()
            or any(ord(c) < 32 for c in self.calendar_version)
        ):
            raise ValueError("Exact owner/account/calendar identity is required.")
        if (
            type(self.period) is not SourcePeriod
            or type(self.candidates) is not tuple
            or not 0 <= len(self.candidates) <= 4
            or any(type(x) is not RetainedSourceCandidate for x in self.candidates)
            or len({x.snapshot_id for x in self.candidates}) != len(self.candidates)
            or (not self.candidates and self.acquisition is None)
        ):
            raise ValueError("At most four explicit unique retained candidates are supported.")
        if self.acquisition is not None and type(self.acquisition) is not FallbackAcquisitionPin:
            raise ValueError("A fixed optional acquisition pin is required.")
        if (
            type(self.enabled) is not bool
            or type(self.synthetic) is not bool
            or (self.synthetic and self.acquisition is not None)
        ):
            raise ValueError("Synthetic fixtures cannot request a live substitute.")
        if (
            type(self.minimum_coverage) is not Decimal
            or not self.minimum_coverage.is_finite()
            or not 0 < self.minimum_coverage <= 1
            or not isinstance(self.minimum_coverage.as_tuple().exponent, int)
            or cast(int, self.minimum_coverage.as_tuple().exponent) < -18
        ):
            raise ValueError("An exact bounded positive coverage threshold is required.")
        if (
            type(self.accepted_qualities) is not tuple
            or not self.accepted_qualities
            or len(set(self.accepted_qualities)) != len(self.accepted_qualities)
            or any(
                type(x) is not QualityState or x is QualityState.FAILED
                for x in self.accepted_qualities
            )
        ):
            raise ValueError("Accepted original source quality must be explicit.")
        object.__setattr__(self, "source_cutoff_at", require_utc(self.source_cutoff_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceFallbackPlan(_Plan):
    instrument_id: UUID
    currency: CurrencyCode
    basis: PriceBasis

    def __post_init__(self) -> None:
        _Plan.__post_init__(self)
        if (
            type(self.instrument_id) is not UUID
            or type(self.currency) is not CurrencyCode
            or type(self.basis) is not PriceBasis
        ):
            raise ValueError("A fixed canonical price meaning is required.")


@dataclass(frozen=True, slots=True, kw_only=True)
class FxFallbackPlan(_Plan):
    pairs: tuple[FxPair, ...]

    def __post_init__(self) -> None:
        _Plan.__post_init__(self)
        if (
            type(self.pairs) is not tuple
            or not 1 <= len(self.pairs) <= 32
            or any(type(x) is not FxPair for x in self.pairs)
            or len(set(self.pairs)) != len(self.pairs)
        ):
            raise ValueError("At most32 exact FX pairs are required.")


type SourceFallbackPlan = PriceFallbackPlan | FxFallbackPlan


@dataclass(frozen=True, slots=True, kw_only=True)
class FallbackSourceFacts:
    family: Literal["price", "fx"]
    snapshot_id: UUID
    content_digest: str
    provider_id: UUID
    license_version_id: UUID
    calendar_id: UUID
    calendar_version: str
    period: SourcePeriod
    first_known_at: datetime
    original_expires_at: datetime
    latest_observation_at: datetime | None
    expected_count: int
    available_count: int
    quality: QualityState
    synthetic: bool
    instrument_id: UUID | None = None
    currency: CurrencyCode | None = None
    basis: PriceBasis | None = None
    pairs: tuple[FxPair, ...] = ()

    def __post_init__(self) -> None:
        RetainedSourceCandidate(snapshot_id=self.snapshot_id, content_digest=self.content_digest)
        if (
            type(self.calendar_version) is not str
            or not 1 <= len(self.calendar_version) <= 120
            or not self.calendar_version.isascii()
        ):
            raise ValueError("An exact original calendar version is required.")
        if (
            self.family not in {"price", "fx"}
            or any(
                type(x) is not UUID
                for x in (self.provider_id, self.license_version_id, self.calendar_id)
            )
            or type(self.period) is not SourcePeriod
            or type(self.quality) is not QualityState
            or type(self.synthetic) is not bool
        ):
            raise ValueError("Original typed source metadata is required.")
        if (
            type(self.expected_count) is not int
            or type(self.available_count) is not int
            or not 0 <= self.available_count <= self.expected_count <= 100000
        ):
            raise ValueError("Actual bounded source coverage is required.")
        for field in ("first_known_at", "original_expires_at"):
            object.__setattr__(self, field, require_utc(getattr(self, field)))
        if self.latest_observation_at is not None:
            object.__setattr__(
                self, "latest_observation_at", require_utc(self.latest_observation_at)
            )
        if self.original_expires_at <= self.first_known_at:
            raise ValueError("Original source lifetime is invalid.")
        if self.family == "price":
            if (
                type(self.instrument_id) is not UUID
                or type(self.currency) is not CurrencyCode
                or type(self.basis) is not PriceBasis
                or self.pairs
            ):
                raise ValueError("Price meaning cannot be replaced by FX semantics.")
        elif (
            any(x is not None for x in (self.instrument_id, self.currency, self.basis))
            or type(self.pairs) is not tuple
            or len(self.pairs) > 32
            or any(type(x) is not FxPair for x in self.pairs)
            or len(set(self.pairs)) != len(self.pairs)
        ):
            raise ValueError("FX metadata requires its actual complete pair set.")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceFallbackComparison:
    ordinal: int
    kind: Literal["retained", "acquisition"]
    requested_id: UUID
    outcome: Literal["unexamined", "rejected", "selected"]
    reason: SourceFallbackReason | None = None
    source: FallbackSourceFacts | None = None

    def __post_init__(self) -> None:
        if (
            type(self.ordinal) is not int
            or not 0 <= self.ordinal <= 4
            or self.kind not in {"retained", "acquisition"}
            or type(self.requested_id) is not UUID
            or self.outcome not in {"unexamined", "rejected", "selected"}
        ):
            raise ValueError("A fixed ordered comparison is required.")
        if self.reason is not None and type(self.reason) is not SourceFallbackReason:
            raise ValueError("A fixed rejection reason is required.")
        if self.source is not None and type(self.source) is not FallbackSourceFacts:
            raise ValueError("Original source facts are required.")
        if self.outcome == "selected" and (self.reason is not None or self.source is None):
            raise ValueError("Selection requires exact compatible evidence.")
        if self.outcome == "unexamined" and (
            self.source is not None or self.reason not in {None, SourceFallbackReason.DISABLED}
        ):
            raise ValueError("Unexamined candidates cannot carry invented evidence.")
        if self.outcome == "rejected" and self.reason is None:
            raise ValueError("Rejected candidates require an explicit reason.")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceFallbackResult:
    account_id: UUID
    selected: FallbackSourceFacts | None
    comparisons: tuple[SourceFallbackComparison, ...]
    method_version: Literal["explicit_source_fallback_v1"] = "explicit_source_fallback_v1"

    def __post_init__(self) -> None:
        if (
            type(self.account_id) is not UUID
            or self.method_version != "explicit_source_fallback_v1"
            or type(self.comparisons) is not tuple
            or not 1 <= len(self.comparisons) <= 5
            or any(type(x) is not SourceFallbackComparison for x in self.comparisons)
            or tuple(x.ordinal for x in self.comparisons) != tuple(range(len(self.comparisons)))
        ):
            raise ValueError("An exact bounded comparison result is required.")
        choices = tuple(x.source for x in self.comparisons if x.outcome == "selected")
        if choices != (() if self.selected is None else (self.selected,)):
            raise ValueError("Exactly the selected source must be identified.")


class CompatibleSourceReader(Protocol):
    async def inspect_price(
        self, principal: Principal, plan: PriceFallbackPlan, candidate: RetainedSourceCandidate
    ) -> FallbackSourceFacts: ...
    async def inspect_fx(
        self, principal: Principal, plan: FxFallbackPlan, candidate: RetainedSourceCandidate
    ) -> FallbackSourceFacts: ...


class CompatibleSourceAcquisition(Protocol):
    async def acquire_price(
        self, principal: Principal, plan: PriceFallbackPlan
    ) -> RetainedSourceCandidate: ...
    async def acquire_fx(
        self, principal: Principal, plan: FxFallbackPlan
    ) -> RetainedSourceCandidate: ...


def compatibility(
    plan: SourceFallbackPlan, value: FallbackSourceFacts
) -> SourceFallbackReason | None:
    reason = SourceFallbackReason
    if (value.family == "price") != (type(plan) is PriceFallbackPlan):
        return reason.INCOMPATIBLE_BASIS
    if value.synthetic != plan.synthetic:
        return reason.SYNTHETIC_MISMATCH
    if (value.calendar_id, value.calendar_version) != (plan.calendar_id, plan.calendar_version):
        return reason.INCOMPATIBLE_CALENDAR
    if value.period != plan.period:
        return reason.INCOMPATIBLE_PERIOD
    if value.first_known_at > plan.source_cutoff_at or (
        value.latest_observation_at is not None
        and value.latest_observation_at > plan.source_cutoff_at
    ):
        return reason.SOURCE_AFTER_CUTOFF
    if isinstance(plan, PriceFallbackPlan):
        if value.instrument_id != plan.instrument_id:
            return reason.INCOMPATIBLE_SUBJECT
        if value.currency != plan.currency:
            return reason.INCOMPATIBLE_CURRENCY
        if value.basis != plan.basis:
            return reason.INCOMPATIBLE_BASIS
    elif set(value.pairs) != set(plan.pairs):
        return reason.INCOMPATIBLE_PAIRS
    if not value.expected_count:
        return reason.INSUFFICIENT_COVERAGE
    with localcontext(Context(prec=96)):
        if Decimal(value.available_count) < Decimal(value.expected_count) * plan.minimum_coverage:
            return reason.INSUFFICIENT_COVERAGE
    if value.quality not in plan.accepted_qualities:
        return reason.QUALITY_NOT_ACCEPTED
    return None


class ExplicitSourceFallback:
    """At most four retained examinations and one fixed matching acquisition."""

    def __init__(
        self,
        reader: CompatibleSourceReader,
        *,
        acquisition: CompatibleSourceAcquisition | None = None,
    ) -> None:
        self._reader, self._acquisition = reader, acquisition

    async def select_price(
        self, principal: Principal, plan: PriceFallbackPlan
    ) -> SourceFallbackResult:
        if type(plan) is not PriceFallbackPlan:
            raise ValueError("A fixed price plan is required.")
        return await self._select(principal, plan)

    async def select_fx(self, principal: Principal, plan: FxFallbackPlan) -> SourceFallbackResult:
        if type(plan) is not FxFallbackPlan:
            raise ValueError("A fixed FX plan is required.")
        return await self._select(principal, plan)

    async def _inspect(
        self, principal: Principal, plan: SourceFallbackPlan, candidate: RetainedSourceCandidate
    ) -> FallbackSourceFacts:
        value = (
            await self._reader.inspect_price(principal, plan, candidate)
            if isinstance(plan, PriceFallbackPlan)
            else await self._reader.inspect_fx(principal, plan, candidate)
        )
        if (
            value.snapshot_id != candidate.snapshot_id
            or value.content_digest != candidate.content_digest
        ):
            raise SourceFallbackError(SourceFallbackReason.CONTENT_MISMATCH)
        return value

    async def _select(self, principal: Principal, plan: SourceFallbackPlan) -> SourceFallbackResult:
        entries = [
            SourceFallbackComparison(
                ordinal=i,
                kind="retained",
                requested_id=x.snapshot_id,
                outcome="unexamined",
                reason=SourceFallbackReason.DISABLED if not plan.enabled else None,
            )
            for i, x in enumerate(plan.candidates)
        ]
        if plan.acquisition is not None:
            entries.append(
                SourceFallbackComparison(
                    ordinal=len(entries),
                    kind="acquisition",
                    requested_id=plan.acquisition.request_id,
                    outcome="unexamined",
                    reason=SourceFallbackReason.DISABLED if not plan.enabled else None,
                )
            )
        if not plan.enabled:
            return SourceFallbackResult(
                account_id=plan.account_id, selected=None, comparisons=tuple(entries)
            )
        try:
            owner = UUID(principal.owner_id)
        except ValueError:
            raise SourceFallbackError(SourceFallbackReason.ACCESS_DENIED) from None
        if owner != plan.owner_id:
            raise SourceFallbackError(SourceFallbackReason.ACCESS_DENIED)
        selected = None
        for index in range(len(entries)):
            try:
                if index < len(plan.candidates):
                    candidate = plan.candidates[index]
                else:
                    if self._acquisition is None:
                        raise SourceFallbackError(SourceFallbackReason.ACQUISITION_UNAVAILABLE)
                    candidate = (
                        await self._acquisition.acquire_price(principal, plan)
                        if isinstance(plan, PriceFallbackPlan)
                        else await self._acquisition.acquire_fx(principal, plan)
                    )
                value = await self._inspect(principal, plan, candidate)
                failure = compatibility(plan, value)
                entries[index] = replace(
                    entries[index],
                    outcome="selected" if failure is None else "rejected",
                    reason=failure,
                    source=value,
                )
                if failure is None:
                    selected = value
                    break
            except SourceFallbackError as failure:
                if failure.reason is SourceFallbackReason.ACCESS_DENIED:
                    raise
                entries[index] = replace(entries[index], outcome="rejected", reason=failure.reason)
        # Even rejected-but-authorized comparison metadata must still be permitted
        # at return. Redact a revoked candidate instead of returning stale proof.
        for index, entry in enumerate(entries):
            if entry.source is None:
                continue
            try:
                current = await self._inspect(
                    principal,
                    plan,
                    RetainedSourceCandidate(
                        snapshot_id=entry.source.snapshot_id,
                        content_digest=entry.source.content_digest,
                    ),
                )
                if current != entry.source:
                    raise SourceFallbackError(SourceFallbackReason.SOURCE_UNAVAILABLE)
            except SourceFallbackError as failure:
                if failure.reason is SourceFallbackReason.ACCESS_DENIED:
                    raise
                if entry.outcome == "selected":
                    selected = None
                entries[index] = replace(
                    entry,
                    outcome="rejected",
                    reason=SourceFallbackReason.SOURCE_UNAVAILABLE,
                    source=None,
                )
        return SourceFallbackResult(
            account_id=plan.account_id, selected=selected, comparisons=tuple(entries)
        )
