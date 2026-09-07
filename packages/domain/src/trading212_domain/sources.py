"""Closed, immutable reference-source records; no transport or provider payloads."""

from __future__ import annotations

import hashlib
import re
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .enums import QualityState
from .errors import fail_validation
from .serialization import canonical_json, to_primitive
from .values import CurrencyCode, exact_decimal, require_bounded_text, require_utc

if TYPE_CHECKING:
    from .source_details import CorporateActionSnapshot

SOURCE_SCHEMA_VERSION = "1.0.0"
SOURCE_METHOD_VERSION = "1.0.0"
SOURCE_QUANTUM = Decimal("0.000000000000000001")
MAX_SOURCE_ROWS = 100_000
MAX_SOURCE_PAGE_ROWS = 1000
MAX_SOURCE_PAGES = 100
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")


class SourceSeriesKind(StrEnum):
    SECURITY_PRICE = "security_price"
    BENCHMARK_LEVEL = "benchmark_level"


class PriceBasis(StrEnum):
    RAW_CLOSE = "raw_close"
    SPLIT_ADJUSTED = "split_adjusted"
    TOTAL_RETURN = "total_return"


class BenchmarkSnapshotKind(StrEnum):
    PROVIDER_SERIES = "provider_series"
    COMPOSITE = "composite"


class SourceAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class ObservationState(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"
    DISPUTED = "disputed"


class LicensePermission(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class SourceUse(StrEnum):
    STORE = "store"
    DISPLAY = "display"
    REPORT = "report"
    EXPORT = "export"


class SourceReason(StrEnum):
    NO_OBSERVATIONS = "no_observations"
    MISSING_SESSION = "missing_session"
    OUTSIDE_CALENDAR = "outside_calendar"
    BEFORE_FIRST_OBSERVATION = "before_first_observation"
    FUTURE_OBSERVATION = "future_observation"
    AFTER_CUTOFF = "after_cutoff"
    STALE = "stale"
    UNSUPPORTED = "unsupported"
    DISPUTED = "disputed"
    AMBIGUOUS_REVISION = "ambiguous_revision"
    MISSING_FX_PAIR = "missing_fx_pair"
    INCOMPATIBLE_FIXING = "incompatible_fixing"
    NUMERIC_UNREPRESENTABLE = "numeric_unrepresentable"
    LICENSE_DENIED = "license_denied"
    EXPIRED = "expired"
    NOT_CONFIGURED = "not_configured"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    RETENTION_REMOVED = "retention_removed"


def source_id(value: str, field: str = "id") -> str:
    if not isinstance(value, str):
        fail_validation("A canonical UUID is required.", field=field)
    parsed: UUID | None = None
    with suppress(ValueError):
        parsed = UUID(value)
    if parsed is None or str(parsed) != value:
        fail_validation("A canonical UUID is required.", field=field)
    return value


def source_key(value: str, field: str = "key") -> str:
    if not isinstance(value, str) or not _KEY.fullmatch(value):
        fail_validation("A bounded canonical source key is required.", field=field)
    return value


def source_tuple[T](
    value: tuple[T, ...], kind: type[T] | tuple[type[T], ...], field: str, maximum: int
) -> None:
    if (
        not isinstance(value, tuple)
        or len(value) > maximum
        or any(not isinstance(item, kind) for item in value)
    ):
        fail_validation("A bounded immutable typed collection is required.", field=field)


def source_integer(value: int, field: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        fail_validation("An integer within the supported bounds is required.", field=field)


def _typed(value: object, kind: type[object] | tuple[type[object], ...], field: str) -> None:
    if not isinstance(value, kind):
        fail_validation("A typed canonical source value is required.", field=field)


def _date(value: date, field: str) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        fail_validation("A calendar date is required.", field=field)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourcePeriod:
    start: date
    end: date

    def __post_init__(self) -> None:
        _date(self.start, "period.start")
        _date(self.end, "period.end")
        if not 0 <= (self.end - self.start).days <= 3660:
            fail_validation("The inclusive source period exceeds supported bounds.", field="period")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceLicense:
    id: str
    provider_id: str
    version: str
    effective_at: datetime
    store: LicensePermission
    display: LicensePermission
    report: LicensePermission
    export: LicensePermission
    retention_days: int | None
    attribution: str
    evidence_key: str

    def __post_init__(self) -> None:
        source_id(self.id)
        source_id(self.provider_id, "provider_id")
        source_key(self.version, "version")
        source_key(self.evidence_key, "evidence_key")
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        for field in ("store", "display", "report", "export"):
            _typed(getattr(self, field), LicensePermission, field)
        if self.retention_days is not None:
            source_integer(self.retention_days, "retention_days", 1, 36500)
        if self.store is LicensePermission.ALLOWED and self.retention_days is None:
            fail_validation(
                "Permitted storage requires an explicit retention bound.", field="retention_days"
            )
        require_bounded_text(self.attribution, field="attribution", maximum=2000)

    def permits(self, use: SourceUse) -> bool:
        _typed(use, SourceUse, "use")
        return getattr(self, use.value) is LicensePermission.ALLOWED


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceSeries:
    id: str
    owner_id: str
    provider_id: str
    license_version_id: str
    kind: SourceSeriesKind
    provider_key: str
    mapping_version: str
    basis: PriceBasis
    currency: CurrencyCode
    calendar_id: str
    calendar_version: str
    mapping_id: str | None = None
    instrument_id: str | None = None
    listing_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("id", "owner_id", "provider_id", "license_version_id"):
            source_id(getattr(self, field), field)
        for field in ("provider_key", "mapping_version", "calendar_id", "calendar_version"):
            source_key(getattr(self, field), field)
        for field in ("mapping_id", "instrument_id", "listing_id"):
            if getattr(self, field) is not None:
                source_id(getattr(self, field), field)
        _typed(self.kind, SourceSeriesKind, "kind")
        _typed(self.basis, PriceBasis, "basis")
        _typed(self.currency, CurrencyCode, "currency")
        if self.kind is SourceSeriesKind.SECURITY_PRICE:
            if self.mapping_id is None or self.instrument_id is None:
                fail_validation(
                    "A security series requires a resolved immutable mapping.", field="mapping_id"
                )
        elif any(x is not None for x in (self.mapping_id, self.instrument_id, self.listing_id)):
            fail_validation(
                "Benchmark levels cannot fabricate security mappings.", field="mapping_id"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceProvenance:
    provider_id: str
    license_version_id: str
    adapter_version: str
    schema_version: str
    source_revision: str
    revision_order: int | None
    effective_at: datetime
    first_observed_at: datetime
    synthetic: bool

    def __post_init__(self) -> None:
        source_id(self.provider_id, "provider_id")
        source_id(self.license_version_id, "license_version_id")
        for field in ("adapter_version", "schema_version", "source_revision"):
            source_key(getattr(self, field), field)
        if self.revision_order is not None:
            source_integer(self.revision_order, "revision_order", 0, 2**63 - 1)
        for field in ("effective_at", "first_observed_at"):
            object.__setattr__(self, field, require_utc(getattr(self, field), field=field))
        if type(self.synthetic) is not bool:
            fail_validation("A boolean source classification is required.", field="synthetic")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceGap:
    session_date: date
    reason: SourceReason
    source_key: str | None = None

    def __post_init__(self) -> None:
        _date(self.session_date, "session_date")
        _typed(self.reason, SourceReason, "reason")
        if self.source_key is not None:
            source_key(self.source_key)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceCoverage:
    expected_count: int
    available_count: int
    gaps: tuple[SourceGap, ...]
    quality: QualityState
    reason: SourceReason | None = None

    def __post_init__(self) -> None:
        source_integer(self.expected_count, "expected_count", 0, MAX_SOURCE_ROWS)
        source_integer(self.available_count, "available_count", 0, self.expected_count)
        source_tuple(self.gaps, SourceGap, "gaps", MAX_SOURCE_ROWS)
        _typed(self.quality, QualityState, "quality")
        if self.reason is not None:
            _typed(self.reason, SourceReason, "reason")
        if (
            len({(x.session_date, x.source_key) for x in self.gaps}) != len(self.gaps)
            or self.available_count + len(self.gaps) > self.expected_count
        ):
            fail_validation(
                "Coverage gaps must be unique and within expected counts.", field="gaps"
            )
        if self.quality is QualityState.FRESH and (
            self.available_count != self.expected_count or self.gaps
        ):
            fail_validation("Fresh coverage cannot contain missing observations.", field="coverage")


def _observation(
    value: PriceObservation | FxObservation | BenchmarkObservation, *, field: str
) -> None:
    _date(value.session_date, "session_date")
    object.__setattr__(value, "effective_at", require_utc(value.effective_at))
    state = value.state
    _typed(state, ObservationState, "state")
    amount = getattr(value, field)
    if state is ObservationState.AVAILABLE:
        if amount is None:
            fail_validation("Available observations require a positive exact value.", field=field)
        amount = exact_decimal(amount, field=field)
        if amount <= 0:
            fail_validation("Available observations require a positive exact value.", field=field)
        object.__setattr__(value, field, amount)
    elif amount is not None:
        fail_validation("Unavailable observations cannot carry a substituted value.", field=field)


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceObservation:
    session_date: date
    effective_at: datetime
    value: Decimal | None
    state: ObservationState = ObservationState.AVAILABLE
    corporate_action_revision: str | None = None

    def __post_init__(self) -> None:
        _observation(self, field="value")
        if self.corporate_action_revision is not None:
            source_key(self.corporate_action_revision, "corporate_action_revision")


@dataclass(frozen=True, slots=True, kw_only=True)
class FxObservation:
    base: CurrencyCode
    quote: CurrencyCode
    session_date: date
    effective_at: datetime
    rate: Decimal | None
    batch_key: str
    state: ObservationState = ObservationState.AVAILABLE

    def __post_init__(self) -> None:
        _observation(self, field="rate")
        _typed(self.base, CurrencyCode, "base")
        _typed(self.quote, CurrencyCode, "quote")
        source_key(self.batch_key, "batch_key")
        if self.base == self.quote:
            fail_validation("Provider FX observations require distinct currencies.", field="quote")


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkObservation:
    session_date: date
    effective_at: datetime
    level: Decimal | None
    state: ObservationState = ObservationState.AVAILABLE

    def __post_init__(self) -> None:
        _observation(self, field="level")


def _snapshot(value: SourceSnapshot | CorporateActionSnapshot, kind: type[object]) -> None:
    source_id(value.id)
    source_id(value.owner_id, "owner_id")
    provenance = value.provenance
    period = value.period
    _typed(provenance, SourceProvenance, "provenance")
    _typed(period, SourcePeriod, "period")
    _typed(value.coverage, SourceCoverage, "coverage")
    observations = value.observations
    source_tuple(observations, kind, "observations", MAX_SOURCE_ROWS)
    keys = []
    for observation in observations:
        if not period.start <= observation.session_date <= period.end:
            fail_validation("An observation is outside its declared period.", field="observations")
        keys.append(
            (
                observation.session_date,
                getattr(observation, "base", None),
                getattr(observation, "quote", None),
                getattr(observation, "source_key", None),
            )
        )
    if len(keys) != len(set(keys)):
        fail_validation(
            "Duplicate source observation identities are not allowed.", field="observations"
        )
    if value.coverage.available_count != sum(
        observation.state is ObservationState.AVAILABLE for observation in observations
    ):
        fail_validation(
            "Snapshot coverage must agree with its complete observations.", field="coverage"
        )
    object.__setattr__(
        value,
        "observations",
        tuple(
            item
            for _, item in sorted(zip(keys, observations, strict=True), key=lambda item: item[0])
        ),
    )


def _series_snapshot(
    value: PriceSnapshot | BenchmarkSnapshot | CorporateActionSnapshot, kind: SourceSeriesKind
) -> None:
    series = value.series
    _typed(series, SourceSeries, "series")
    assert isinstance(series, SourceSeries)
    if (
        series.kind is not kind
        or series.owner_id != value.owner_id
        or series.provider_id != value.provenance.provider_id
        or series.license_version_id != value.provenance.license_version_id
    ):
        fail_validation("Snapshot source scope must match its immutable series.", field="series")


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceSnapshot:
    id: str
    owner_id: str
    series: SourceSeries
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    observations: tuple[PriceObservation, ...]

    def __post_init__(self) -> None:
        _snapshot(self, PriceObservation)
        _series_snapshot(self, SourceSeriesKind.SECURITY_PRICE)


@dataclass(frozen=True, slots=True, kw_only=True)
class FxSnapshot:
    id: str
    owner_id: str
    calendar_id: str
    calendar_version: str
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    observations: tuple[FxObservation, ...]

    def __post_init__(self) -> None:
        source_key(self.calendar_id, "calendar_id")
        source_key(self.calendar_version, "calendar_version")
        _snapshot(self, FxObservation)


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkSnapshot:
    id: str
    owner_id: str
    series: SourceSeries | None
    provenance: SourceProvenance
    period: SourcePeriod
    coverage: SourceCoverage
    observations: tuple[BenchmarkObservation, ...]
    kind: BenchmarkSnapshotKind = BenchmarkSnapshotKind.PROVIDER_SERIES
    benchmark_version_id: str | None = None

    def __post_init__(self) -> None:
        _snapshot(self, BenchmarkObservation)
        _typed(self.kind, BenchmarkSnapshotKind, "kind")
        if self.kind is not BenchmarkSnapshotKind.PROVIDER_SERIES:
            fail_validation(
                "Composite benchmark calculation is not a provider source operation.", field="kind"
            )
        if self.benchmark_version_id is not None:
            fail_validation(
                "Raw benchmark sources cannot reference a composite version.",
                field="benchmark_version_id",
            )
        _series_snapshot(self, SourceSeriesKind.BENCHMARK_LEVEL)


type SourceSnapshot = PriceSnapshot | FxSnapshot | BenchmarkSnapshot


def source_snapshot_digest(snapshot: SourceSnapshot | CorporateActionSnapshot) -> str:
    """Hash minimized economic data, retaining actual knowledge time separately."""
    from .source_details import CorporateActionSnapshot

    _typed(
        snapshot,
        (PriceSnapshot, FxSnapshot, BenchmarkSnapshot, CorporateActionSnapshot),
        "snapshot",
    )
    value = to_primitive(snapshot)
    if not isinstance(value, dict) or not isinstance(value.get("provenance"), dict):
        fail_validation("A canonical source snapshot is required.", field="snapshot")
    value.pop("id")
    value["provenance"].pop("first_observed_at")
    coverage = value["coverage"]
    assert isinstance(coverage, dict) and isinstance(coverage["gaps"], list)
    coverage["gaps"] = sorted(coverage["gaps"], key=canonical_json)
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class RetrievalOccurrence:
    id: str
    snapshot_id: str
    retrieved_at: datetime

    def __post_init__(self) -> None:
        source_id(self.id)
        source_id(self.snapshot_id, "snapshot_id")
        object.__setattr__(self, "retrieved_at", require_utc(self.retrieved_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class MarketSession:
    session_date: date
    close_at: datetime

    def __post_init__(self) -> None:
        _date(self.session_date, "session_date")
        object.__setattr__(self, "close_at", require_utc(self.close_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceCalendar:
    id: str
    version: str
    timezone: str
    period: SourcePeriod
    sessions: tuple[MarketSession, ...]

    def __post_init__(self) -> None:
        source_key(self.id, "calendar_id")
        source_key(self.version, "calendar_version")
        require_bounded_text(self.timezone, field="timezone", maximum=80)
        zone: ZoneInfo | None = None
        with suppress(ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo(self.timezone)
        if zone is None:
            fail_validation("A supported named calendar timezone is required.", field="timezone")
        _typed(self.period, SourcePeriod, "period")
        source_tuple(self.sessions, MarketSession, "sessions", 3661)
        dates = [x.session_date for x in self.sessions]
        if dates != sorted(set(dates)):
            fail_validation("Calendar sessions must be unique and ordered.", field="sessions")
        for session in self.sessions:
            if (
                not self.period.start <= session.session_date <= self.period.end
                or session.close_at.astimezone(zone).date() != session.session_date
            ):
                fail_validation("Session date and named calendar must agree.", field="sessions")


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceSelectionPolicy:
    version: str
    provider_priority: tuple[str, ...]
    max_age_seconds: int
    allow_closed_session_carry: bool = False
    allow_inverse_fx: bool = True
    pivot_currency: CurrencyCode | None = None
    max_missed_sessions: int = 0

    def __post_init__(self) -> None:
        source_key(self.version, "policy.version")
        source_tuple(self.provider_priority, str, "provider_priority", 256)
        if not self.provider_priority or len(set(self.provider_priority)) != len(
            self.provider_priority
        ):
            fail_validation(
                "Provider precedence must be nonempty and unique.", field="provider_priority"
            )
        for provider in self.provider_priority:
            source_id(provider, "provider_priority")
        source_integer(self.max_age_seconds, "max_age_seconds", 0, 315360000)
        source_integer(self.max_missed_sessions, "max_missed_sessions", 0, 0)
        for field in ("allow_closed_session_carry", "allow_inverse_fx"):
            if type(getattr(self, field)) is not bool:
                fail_validation("An explicit boolean policy is required.", field=field)
        if self.pivot_currency is not None:
            _typed(self.pivot_currency, CurrencyCode, "pivot_currency")


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectedSource:
    snapshot_id: str
    content_digest: str
    provider_id: str
    license_version_id: str
    observation_index: int
    effective_at: datetime
    first_observed_at: datetime

    def __post_init__(self) -> None:
        for field in ("snapshot_id", "provider_id", "license_version_id"):
            source_id(getattr(self, field), field)
        if not isinstance(self.content_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.content_digest
        ):
            fail_validation("A canonical source digest is required.", field="content_digest")
        source_integer(self.observation_index, "observation_index", 0, MAX_SOURCE_ROWS - 1)
        for field in ("effective_at", "first_observed_at"):
            object.__setattr__(self, field, require_utc(getattr(self, field)))


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceSelection:
    value: Decimal | None
    currency: CurrencyCode
    availability: SourceAvailability
    reason: SourceReason | None
    selected: SelectedSource | None

    def __post_init__(self) -> None:
        _selected_result(self, "value")


def _selected_result(value: PriceSelection | BenchmarkSelection, field: str) -> None:
    _typed(value.currency, CurrencyCode, "currency")
    _typed(value.availability, SourceAvailability, "availability")
    if value.reason is not None:
        _typed(value.reason, SourceReason, "reason")
    if value.selected is not None:
        _typed(value.selected, SelectedSource, "selected")
    amount = getattr(value, field)
    if amount is not None:
        amount = exact_decimal(amount, field=field)
        if amount <= 0 or value.selected is None:
            fail_validation(
                "Selected source values require positive exact data and provenance.", field=field
            )
        object.__setattr__(value, field, amount)
    elif value.availability is SourceAvailability.AVAILABLE:
        fail_validation("An available selection requires a value.", field=field)
    if value.availability is not SourceAvailability.AVAILABLE and value.reason is None:
        fail_validation("A nonavailable source selection requires a reason.", field="reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkSelection:
    level: Decimal | None
    currency: CurrencyCode
    availability: SourceAvailability
    reason: SourceReason | None
    selected: SelectedSource | None

    def __post_init__(self) -> None:
        _selected_result(self, "level")


class FxOperation(StrEnum):
    IDENTITY = "identity"
    DIRECT = "direct"
    RECIPROCAL = "reciprocal"
    TRIANGULATED = "triangulated"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True, kw_only=True)
class FxConversion:
    base: CurrencyCode
    quote: CurrencyCode
    rate: Decimal | None
    operation: FxOperation
    availability: SourceAvailability
    reason: SourceReason | None
    sources: tuple[SelectedSource, ...]

    def __post_init__(self) -> None:
        _typed(self.base, CurrencyCode, "base")
        _typed(self.quote, CurrencyCode, "quote")
        _typed(self.operation, FxOperation, "operation")
        _typed(self.availability, SourceAvailability, "availability")
        source_tuple(self.sources, SelectedSource, "sources", 2)
        if self.reason is not None:
            _typed(self.reason, SourceReason, "reason")
        if self.rate is None:
            if (
                self.availability is SourceAvailability.AVAILABLE
                or self.operation is not FxOperation.UNAVAILABLE
                or self.reason is None
                or self.sources
            ):
                fail_validation("Unavailable conversion fields are inconsistent.", field="rate")
        else:
            object.__setattr__(self, "rate", exact_decimal(self.rate, field="rate"))
            expected = {
                FxOperation.IDENTITY: 0,
                FxOperation.DIRECT: 1,
                FxOperation.RECIPROCAL: 1,
                FxOperation.TRIANGULATED: 2,
            }
            if (
                self.rate <= 0
                or self.availability is not SourceAvailability.AVAILABLE
                or self.reason is not None
                or self.operation not in expected
                or len(self.sources) != expected[self.operation]
            ):
                fail_validation("Available conversion fields are inconsistent.", field="rate")
            if self.operation is FxOperation.IDENTITY and (
                self.base != self.quote or self.rate != 1
            ):
                fail_validation(
                    "Identity FX requires the same currency and exactly one.", field="rate"
                )
            if self.operation is not FxOperation.IDENTITY and self.base == self.quote:
                fail_validation(
                    "Same-currency conversion must be explicit identity.", field="operation"
                )


class BenchmarkRebalanceRule(StrEnum):
    BUY_AND_HOLD = "buy_and_hold"
    DAILY_REBALANCED = "daily_rebalanced"


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkComponent:
    source_id: str
    weight: Decimal

    def __post_init__(self) -> None:
        source_id(self.source_id)
        object.__setattr__(self, "weight", exact_decimal(self.weight, field="weight"))
        if not 0 <= self.weight <= 1:
            fail_validation("Benchmark weights must be fractions in [0, 1].", field="weight")


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkContent:
    reporting_currency: CurrencyCode
    effective_at: datetime
    return_basis: PriceBasis
    calendar_id: str
    calendar_version: str
    rebalance_rule: BenchmarkRebalanceRule
    components: tuple[BenchmarkComponent, ...]

    def __post_init__(self) -> None:
        _typed(self.reporting_currency, CurrencyCode, "reporting_currency")
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        _typed(self.return_basis, PriceBasis, "return_basis")
        _typed(self.rebalance_rule, BenchmarkRebalanceRule, "rebalance_rule")
        source_key(self.calendar_id, "calendar_id")
        source_key(self.calendar_version, "calendar_version")
        source_tuple(self.components, BenchmarkComponent, "components", 256)
        if not self.components or len({x.source_id for x in self.components}) != len(
            self.components
        ):
            fail_validation("Benchmark components must be nonempty and unique.", field="components")


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkNormalizationAdjustment:
    source_id: str
    original_weight: Decimal
    normalized_weight: Decimal

    def __post_init__(self) -> None:
        source_id(self.source_id)
        for field in ("original_weight", "normalized_weight"):
            weight = exact_decimal(getattr(self, field), field=field)
            if not 0 <= weight <= 1:
                fail_validation("A normalized benchmark weight must be a fraction.", field=field)
            object.__setattr__(self, field, weight)


@dataclass(frozen=True, slots=True, kw_only=True)
class BenchmarkValidation:
    content: BenchmarkContent
    adjustments: tuple[BenchmarkNormalizationAdjustment, ...]

    def __post_init__(self) -> None:
        _typed(self.content, BenchmarkContent, "content")
        source_tuple(self.adjustments, BenchmarkNormalizationAdjustment, "adjustments", 256)


def normalize_benchmark_content(
    content: BenchmarkContent, *, normalize: bool = False
) -> BenchmarkValidation:
    _typed(content, BenchmarkContent, "content")
    if type(normalize) is not bool:
        fail_validation("Normalization requires an explicit boolean.", field="normalize")
    components = sorted(content.components, key=lambda x: x.source_id)
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        weight_sum = sum((x.weight for x in components), Decimal(0))
        if weight_sum <= 0 or (
            weight_sum != 1 and (not normalize or abs(weight_sum - 1) > Decimal("0.000000000001"))
        ):
            fail_validation(
                "Benchmark weights must sum exactly one or explicitly normalize within tolerance.",
                field="components",
            )
        if weight_sum == 1:
            return BenchmarkValidation(
                content=replace(content, components=tuple(components)), adjustments=()
            )
        # Floor to exact quanta, then award residual units by remainder and stable ID.
        scaled = [x.weight / weight_sum / SOURCE_QUANTUM for x in components]
        floors = [int(x) for x in scaled]
        remaining = int(Decimal(1) / SOURCE_QUANTUM) - sum(floors)
        order = sorted(
            range(len(components)),
            key=lambda i: (-(scaled[i] - floors[i]), components[i].source_id),
        )
        for i in order[:remaining]:
            floors[i] += 1
        normalized = tuple(
            replace(x, weight=Decimal(n) * SOURCE_QUANTUM)
            for x, n in zip(components, floors, strict=True)
        )
    changes = tuple(
        BenchmarkNormalizationAdjustment(
            source_id=a.source_id, original_weight=a.weight, normalized_weight=b.weight
        )
        for a, b in zip(components, normalized, strict=True)
        if a.weight != b.weight
    )
    return BenchmarkValidation(content=replace(content, components=normalized), adjustments=changes)
