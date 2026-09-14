"""Shared bounded historical reconstruction and actual-use source selection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from functools import wraps
from hashlib import sha256
from typing import Literal

from trading212_domain import CurrencyCode, Money, QualityState
from trading212_domain import historical as d
from trading212_domain import historical_results as r
from trading212_domain.errors import DomainError, ErrorCode, fail_validation
from trading212_domain.historical_serialization import historical_input_digest
from trading212_domain.planning import CoveragePolicy
from trading212_domain.serialization import canonical_json
from trading212_domain.source_details import CorporateActionKind, CorporateActionSnapshot
from trading212_domain.sources import (
    BenchmarkSnapshot,
    FxObservation,
    FxOperation,
    FxSnapshot,
    ObservationState,
    PriceBasis,
    PriceSnapshot,
    SelectedSource,
    SourceAvailability,
    SourceCalendar,
    source_snapshot_digest,
)

from ._decimal import persisted_decimal
from ._historical_actions import select_actions
from ._selection_index import (
    MAX_INDEX_CANDIDATES,
    MAX_INDEX_SERIES,
    CalendarIndex,
    CalendarSelectionIndex,
)
from .source_policy import _source_digest_scope, select_benchmark, select_fx, select_price

ZERO = Decimal(0)
ONE = Decimal(1)


def financial[**P, T](function: Callable[P, T]) -> Callable[P, T]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        with _source_digest_scope(), localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
            return function(*args, **kwargs)

    return wrapped


def elapsed(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    return Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1000000


def key(*values: object) -> str:
    return sha256(canonical_json(values).encode("utf-8")).hexdigest()


def money_metric(
    amount: Decimal | None,
    currency: CurrencyCode,
    *,
    reason: d.HistoricalReason = d.HistoricalReason.VALUATION_MISSING,
    coverage: d.HistoricalCoverageKey = d.HistoricalCoverageKey.VALUATIONS,
    partial: bool = False,
    quality: QualityState = QualityState.FRESH,
) -> d.HistoricalMoneyMetric:
    return d.HistoricalMoneyMetric(
        value=Money(persisted_decimal(amount), currency) if amount is not None else None,
        availability=d.MetricAvailability.UNAVAILABLE
        if amount is None
        else d.MetricAvailability.PARTIAL
        if partial
        else d.MetricAvailability.AVAILABLE,
        reason_code=reason if amount is None or partial else None,
        quality=QualityState.PARTIAL
        if amount is None
        else QualityState.PARTIAL
        if partial
        else quality,
        coverage_key=coverage,
    )


def ratio_metric(
    amount: Decimal | None,
    *,
    reason: d.HistoricalReason = d.HistoricalReason.VALUATION_MISSING,
    coverage: d.HistoricalCoverageKey = d.HistoricalCoverageKey.VALUATIONS,
    partial: bool = False,
) -> d.HistoricalRatioMetric:
    return d.HistoricalRatioMetric(
        value=persisted_decimal(amount) if amount is not None else None,
        availability=d.MetricAvailability.UNAVAILABLE
        if amount is None
        else d.MetricAvailability.PARTIAL
        if partial
        else d.MetricAvailability.AVAILABLE,
        reason_code=reason if amount is None or partial else None,
        quality=QualityState.PARTIAL
        if amount is None
        else QualityState.PARTIAL
        if partial
        else QualityState.FRESH,
        coverage_key=coverage,
    )


def amount(metric: d.HistoricalMoneyMetric) -> Decimal | None:
    return metric.value.amount if metric.value is not None else None


def known(metric: d.HistoricalMoneyMetric) -> Money | None:
    return metric.value if metric.availability is d.MetricAvailability.AVAILABLE else None


def dividend_parts(
    engine: HistoricalEngine, event: d.HistoricalDividend
) -> tuple[Money | None, Money | None]:
    """Known gross and tax must reconcile to the observed net in one sourced currency."""
    gross, tax = known(event.gross), known(event.withholding)
    if gross is None or tax is None:
        return gross, tax
    if gross.currency == tax.currency == event.net.currency:
        reconciled = gross.amount - tax.amount == event.net.amount
    else:
        consumer = r.HistoricalUseConsumer(
            kind="event", event_revision_id=event.identity.revision_id
        )
        values = tuple(
            engine.convert(item, event.identity.economic_at, consumer)
            for item in (gross, tax, event.net)
        )
        if any(item is None for item in values):
            return gross, tax
        g, t, n = values
        assert g is not None and t is not None and n is not None
        reconciled = abs(g - t - n) <= Decimal("0.000000000000000002")
    if not reconciled:
        engine.warnings.add(d.HistoricalReason.PARTIAL_COVERAGE)
        return None, None
    return gross, tax


def close_boundaries(value: d.HistoricalInput) -> tuple[datetime, ...]:
    window = value.selection.window
    return tuple(
        window.start_at + timedelta(days=i + 1)
        for i in range((window.end_date - window.start_date).days + 1)
    )


def projection_boundaries(
    value: d.HistoricalInput, frequency: d.HistoricalFrequency
) -> tuple[datetime, ...]:
    daily = close_boundaries(value)
    if frequency is d.HistoricalFrequency.DAILY:
        return daily
    return tuple(at for at in daily if at.day == 1 or at == value.selection.window.end_at)


def event_revision_key(event: d.HistoricalEvent) -> str:
    """The canonical economic identity used by revision selection and trusted attestations."""
    return (
        key("fill", event.order_key, event.fill_key)
        if isinstance(event, d.HistoricalExecution)
        else key("dividend", event.dividend_key)
        if isinstance(event, d.HistoricalDividend)
        else event.identity.economic_key
    )


def _attested_revision_edges(
    events: tuple[d.HistoricalEvent, ...], sources: tuple[d.HistoricalSourceReference, ...]
) -> dict[str, tuple[str, datetime]]:
    """Validate explicit retained edges independently of raw provider revision fields."""
    if len(events) > d.MAX_HISTORICAL_EVENTS or len(sources) > d.MAX_HISTORICAL_SOURCES:
        raise DomainError(ErrorCode.INPUT_BOUND_EXCEEDED, "Historical revision capacity exceeded.")
    proofs = tuple(source for source in sources if source.kind == "activity_revision_evidence")
    if not proofs:
        return {}
    by_source = {event.identity.source_record_id: event for event in events}
    by_revision = {event.identity.revision_id: event for event in events}
    if len(by_source) != len(events) or len(by_revision) != len(events):
        fail_validation("Historical revision source identity is duplicated.")
    edges: dict[str, tuple[str, datetime]] = {}
    proof_ids: set[str] = set()
    for proof in proofs:
        if len(proof.parent_ids) != 2 or proof.semantic_digest is None or proof.id in proof_ids:
            fail_validation("Historical revision proof lacks its exact source parents.")
        proof_ids.add(proof.id)
        new_id, old_id = proof.parent_ids
        new, old = by_source.get(new_id), by_source.get(old_id)
        if (
            new is None
            or old is None
            or new_id == old_id
            or new_id in edges
            or event_revision_key(new) != event_revision_key(old)
            or new.identity.supersedes_revision_id not in (None, old.identity.revision_id)
            or (isinstance(new, d.HistoricalDividend) and new.correction_of not in (None, old_id))
        ):
            fail_validation("Historical revision proof has conflicting source parents.")
        edges[new_id] = (old_id, proof.first_observed_at)
    # Reject cycles reachable from proofs, including through native edges. Native
    # groups without proofs keep the selector's established behavior.
    parents = {
        source_id: parent.identity.source_record_id
        for source_id, event in by_source.items()
        if (parent := by_revision.get(event.identity.supersedes_revision_id or "")) is not None
        and event_revision_key(parent) == event_revision_key(event)
    }
    parents.update({source_id: edge[0] for source_id, edge in edges.items()})
    visited: set[str] = set()
    for source_id in edges:
        path: set[str] = set()
        current = source_id
        while current in parents and current not in visited:
            if current in path:
                fail_validation("Historical revision proof has a cycle.")
            path.add(current)
            current = parents[current]
        visited.update(path)
    return edges


def revision_first_eligible_at(
    events: tuple[d.HistoricalEvent, ...],
    sources: tuple[d.HistoricalSourceReference, ...],
    *,
    cutoff: datetime,
) -> dict[str, datetime]:
    """Actual source knowledge plus only the validated ancestry establishing a winner.

    This operational eligibility projection does not rewrite raw event knowledge.
    Memoized iterative traversal visits each retained edge at most once.
    """
    edges = _attested_revision_edges(events, sources)
    by_source = {event.identity.source_record_id: event for event in events}
    if not edges:
        return {
            source_id: event.identity.first_observed_at for source_id, event in by_source.items()
        }
    by_revision = {event.identity.revision_id: event for event in events}
    parents: dict[str, str] = {}
    proof_times: dict[str, datetime] = {}
    for event in events:
        source_id = event.identity.source_record_id
        native = by_revision.get(event.identity.supersedes_revision_id or "")
        if native is not None and event_revision_key(native) == event_revision_key(event):
            parents[source_id] = native.identity.source_record_id
        attested = edges.get(source_id)
        # A redundant attestation cannot postpone an already native correction.
        if attested is not None and attested[1] <= cutoff and native is None:
            parents[source_id] = attested[0]
            proof_times[source_id] = max(
                attested[1],
                event.identity.first_observed_at,
                by_source[attested[0]].identity.first_observed_at,
            )
    # Memoize only proof dependency times. Raw/native observation times keep their
    # existing meaning, even if an unrelated native parent was learned later.
    inherited: dict[str, datetime | None] = {}
    for source_id in by_source:
        current = source_id
        path: list[str] = []
        seen: set[str] = set()
        while current not in inherited:
            if current in seen:
                # Proof-connected cycles were rejected above. An unrelated
                # native cycle remains the canonical selector's ambiguity.
                for member in path:
                    inherited[member] = None
                break
            seen.add(current)
            path.append(current)
            if current not in parents:
                break
            current = parents[current]
        for current in reversed(path):
            parent = parents.get(current)
            times = tuple(
                at
                for at in (proof_times.get(current), inherited.get(parent or ""))
                if at is not None
            )
            inherited[current] = max(times) if times else None
    result: dict[str, datetime] = {}
    for source_id, event in by_source.items():
        proof_at = inherited[source_id]
        # A proof-backed correction becomes eligible only once both its identity
        # and economic applicability are known. Do not change native-only timing.
        result[source_id] = (
            max(event.identity.first_observed_at, event.identity.economic_at, proof_at)
            if proof_at is not None
            else event.identity.first_observed_at
        )
    return result


def selected_events(
    value: d.HistoricalInput, cutoff: datetime
) -> tuple[tuple[d.HistoricalEvent, ...], bool]:
    return selected_event_revisions(value.event_candidates, cutoff, revision_sources=value.sources)


@financial
def selected_event_revisions(
    events: tuple[d.HistoricalEvent, ...],
    cutoff: datetime,
    *,
    revision_sources: tuple[d.HistoricalSourceReference, ...] = (),
) -> tuple[tuple[d.HistoricalEvent, ...], bool]:
    """Order changes only with a provider revision order or explicit supersession."""
    edges = _attested_revision_edges(events, revision_sources)
    by_source = {event.identity.source_record_id: event for event in events}
    attested_groups = {
        event_revision_key(by_source[source_id])
        for source_id, edge in edges.items()
        if edge[1] <= cutoff and by_source[source_id].identity.supersedes_revision_id is None
    }
    groups: dict[str, list[d.HistoricalEvent]] = defaultdict(list)
    for event in events:
        edge = edges.get(event.identity.source_record_id)
        if edge is not None and edge[1] <= cutoff and event.identity.supersedes_revision_id is None:
            parent = by_source[edge[0]]
            event = replace(
                event,
                identity=replace(
                    event.identity, supersedes_revision_id=parent.identity.revision_id
                ),
            )
            if isinstance(event, d.HistoricalDividend):
                event = replace(event, correction_of=edge[0])
        if event.identity.first_observed_at <= cutoff and (
            event.identity.economic_at <= cutoff or event_revision_key(event) in attested_groups
        ):
            groups[event_revision_key(event)].append(event)
    selected: list[d.HistoricalEvent] = []
    ambiguous = False
    for candidates in groups.values():
        superseded = {item.identity.supersedes_revision_id for item in candidates}
        candidates = [item for item in candidates if item.identity.revision_id not in superseded]
        if not candidates:
            # A supersession cycle provides no winning economic revision.
            ambiguous = True
            continue
        if all(item.identity.revision_sequence is not None for item in candidates):
            sequence = max(
                item.identity.revision_sequence
                for item in candidates
                if item.identity.revision_sequence is not None
            )
            candidates = [
                item for item in candidates if item.identity.revision_sequence == sequence
            ]
        economics = {
            canonical_json(
                replace(
                    item,
                    identity=replace(
                        item.identity,
                        revision_id="00000000-0000-0000-0000-000000000001",
                        source_record_id="00000000-0000-0000-0000-000000000001",
                        source_occurrence_id=None,
                        first_observed_at=item.identity.economic_at,
                        revision_sequence=None,
                        supersedes_revision_id=None,
                    ),
                )
            )
            for item in candidates
        }
        if len(economics) != 1:
            ambiguous = True
            continue
        chosen = min(candidates, key=lambda item: item.identity.revision_id)
        if chosen.identity.record_state == "reported" and chosen.identity.economic_at <= cutoff:
            selected.append(chosen)
    ordered = tuple(
        sorted(
            selected,
            key=lambda item: (
                item.identity.economic_at,
                item.identity.economic_key,
                item.identity.revision_id,
            ),
        )
    )
    return _deduplicate_linked(ordered), ambiguous


def _deduplicate_linked(events: tuple[d.HistoricalEvent, ...]) -> tuple[d.HistoricalEvent, ...]:
    """Only explicit equal-event linkage suppresses a duplicate cash ledger effect."""
    by_key = {event.identity.economic_key: event for event in events}
    output: list[d.HistoricalEvent] = []
    for event in events:
        duplicate = False
        if isinstance(event, d.HistoricalCashEffect):
            for related in event.related_event_keys:
                parent = by_key.get(related)
                if parent is None or parent.identity.economic_at != event.identity.economic_at:
                    continue
                expected: Money | None = None
                if isinstance(parent, d.HistoricalExecution):
                    expected = (
                        known(parent.fees if event.effect_kind == "fee" else parent.taxes)
                        if event.effect_kind in ("fee", "tax")
                        else None
                    )
                    if expected is not None:
                        expected = Money(-expected.amount, expected.currency)
                elif (
                    isinstance(parent, d.HistoricalDividend)
                    and event.effect_kind == "internal_transfer"
                ):
                    expected = parent.net
                if expected == event.signed_amount:
                    duplicate = True
        if not duplicate:
            output.append(event)
    return tuple(output)


@dataclass(frozen=True, slots=True)
class NativeAmount:
    """Bounded-context intermediate; quantization occurs only at authoritative outputs."""

    amount: Decimal
    currency: CurrencyCode


@dataclass(slots=True)
class State:
    at: datetime
    quantities: dict[str, Decimal]
    cash: dict[CurrencyCode, Decimal]
    costs: dict[str, NativeAmount | None]
    realized: dict[str, Decimal]
    events: tuple[d.HistoricalEvent, ...]
    actions: tuple[tuple[CorporateActionSnapshot, int], ...] = ()
    reasons: set[d.HistoricalReason] = field(default_factory=set)
    quantity_complete: bool = True
    cash_complete: bool = True
    cost_complete: bool = True


@dataclass(frozen=True, slots=True)
class Valuation:
    at: datetime
    state: State
    holdings: dict[str, Decimal | None]
    native_prices: dict[str, Decimal | None]
    rates: dict[CurrencyCode, Decimal | None]
    cash_values: dict[CurrencyCode, Decimal | None]
    invested: Decimal | None
    cash: Decimal | None
    total: Decimal | None
    partial: bool
    exact: bool


class HistoricalEngine:
    def __init__(self, value: d.HistoricalInput) -> None:
        self.value = value
        self.window = value.selection.window
        self.currency = self.window.reporting_currency
        self.calendars = {(item.id, item.version): item for item in value.calendars}
        self.calendar_indexes = {key: CalendarIndex(item) for key, item in self.calendars.items()}
        self.price_sources: dict[str, tuple[PriceSnapshot | BenchmarkSnapshot, ...]] = {}
        self.selection_indexes: dict[str, CalendarSelectionIndex | None] = {}
        self.selection_budget = MAX_INDEX_CANDIDATES
        self.instruments = {item.listing_id: item for item in value.instruments}
        self.references = {item.id: item for item in value.sources}
        self.uses: dict[str, r.HistoricalSourceUse] = {}
        self.conversions: dict[str, r.HistoricalConversionUse] = {}
        self.cells: set[tuple[str, datetime]] = set()
        self.warnings: set[d.HistoricalReason] = set()
        self.primitive_methods: set[tuple[str, str]] = set()
        self.price_cache: dict[tuple[str, datetime, str], Decimal | None] = {}
        self.price_effective_cache: dict[tuple[str, datetime, str], datetime] = {}
        self.fx_cache: dict[tuple[CurrencyCode, CurrencyCode, datetime, str], Decimal | None] = {}
        self.valuation_cache: dict[tuple[datetime, bool], Valuation] = {}
        self.revision_cache: dict[datetime, tuple[tuple[d.HistoricalEvent, ...], bool]] = {}
        self.expected_cells = 0
        self.successful_cells: set[tuple[str, datetime]] = set()
        self.expected_fx = 0
        self.available_fx = 0
        self.action_coverage_checks: dict[datetime, bool] = {}
        self.preflight_cell_bound = self._preflight()

    def _preflight(self) -> int:
        currencies = {self.currency, *(item.native_currency for item in self.value.instruments)}
        for event in self.value.event_candidates:
            native = event_money(event)
            if native is not None:
                currencies.add(native.currency)
        if isinstance(self.value.opening, d.ObservedHistoricalOpening):
            currencies.update(item.currency for item in self.value.opening.anchor.cash)
        if len(currencies) > 32:
            raise DomainError(
                ErrorCode.INPUT_BOUND_EXCEEDED, "Historical currency capacity exceeded."
            )
        instants = {self.window.start_at, self.window.end_at, *close_boundaries(self.value)}
        instants.update(
            event.identity.economic_at
            for event in self.value.event_candidates
            if self.window.start_at <= event.identity.economic_at < self.window.end_at
        )
        instants.update(
            anchor.at
            for anchor in self.value.valuation_anchors
            if self.window.start_at <= anchor.at <= self.window.end_at
        )
        # Income integration and attribution share exact source-session partitions.
        instants.update(
            session.close_at
            for calendar in self.value.calendars
            for session in calendar.sessions
            if self.window.start_at <= session.close_at <= self.window.end_at
        )
        instants.update(
            observation.effective_at
            for snapshot in self.value.action_snapshots
            for observation in snapshot.observations
            if self.window.start_at <= observation.effective_at < self.window.end_at
        )
        components = (
            len(self.value.benchmark_input.content.components) if self.value.benchmark_input else 0
        )
        if (
            len(instants) > 10000
            or len(instants) * (len(self.instruments) + len(currencies) + components)
            > d.MAX_HISTORICAL_CELLS
        ):
            raise DomainError(
                ErrorCode.INPUT_BOUND_EXCEEDED, "Historical valuation-cell capacity exceeded."
            )
        return len(instants) * (len(self.instruments) + len(currencies) + components)

    def cutoff(self, at: datetime) -> datetime:
        return (
            min(self.window.source_cutoff_at, at)
            if self.window.knowledge_policy is d.KnowledgePolicy.POINT_IN_TIME
            else self.window.source_cutoff_at
        )

    def events(self, at: datetime) -> tuple[tuple[d.HistoricalEvent, ...], bool]:
        cutoff = self.cutoff(at)
        if cutoff not in self.revision_cache:
            self.revision_cache[cutoff] = selected_events(self.value, cutoff)
        return self.revision_cache[cutoff]

    def source_transition(self, start: datetime, end: datetime) -> bool:
        """A changed historical observation is a knowledge revision, not investment gain."""
        if self.window.knowledge_policy is not d.KnowledgePolicy.POINT_IN_TIME:
            return False
        source_items: tuple[PriceSnapshot | FxSnapshot, ...] = (
            *self.value.price_snapshots,
            *self.value.fx_snapshots,
        )
        snapshots = {item.id: item for item in source_items}
        policy = self.value.selection.source_policy
        if policy is None:
            return False
        for use in tuple(self.uses.values()):
            if (
                not isinstance(use, r.HistoricalObservationUse)
                or use.use_at != start
                or use.source_kind not in ("price", "fx")
            ):
                continue
            old = snapshots[use.snapshot_id]
            original = old.observations[use.observation_index]
            for candidate in snapshots.values():
                receipt = candidate.provenance.first_observed_at
                if not self.cutoff(start) < receipt <= self.cutoff(
                    end
                ) or candidate.provenance.effective_at > self.cutoff(end):
                    continue
                if (
                    candidate.provenance.provider_id not in policy.provider_priority
                    or policy.provider_priority.index(candidate.provenance.provider_id)
                    > policy.provider_priority.index(old.provenance.provider_id)
                ):
                    continue
                if isinstance(old, PriceSnapshot):
                    if (
                        not isinstance(candidate, PriceSnapshot)
                        or candidate.series.id != old.series.id
                    ):
                        continue
                elif not isinstance(candidate, type(old)):
                    continue
                old_order, new_order = (
                    old.provenance.revision_order,
                    candidate.provenance.revision_order,
                )
                if old_order is not None and new_order is not None and new_order < old_order:
                    continue
                for observation in candidate.observations:
                    if observation.effective_at != original.effective_at:
                        continue
                    if isinstance(original, FxObservation) and (
                        not isinstance(observation, FxObservation)
                        or (observation.base, observation.quote) != (original.base, original.quote)
                    ):
                        continue
                    if isinstance(original, FxObservation) and isinstance(
                        observation, FxObservation
                    ):
                        if (observation.state, observation.rate) != (original.state, original.rate):
                            return True
                    elif observation != original:
                        return True
                if any(
                    gap.session_date == original.session_date for gap in candidate.coverage.gaps
                ):
                    return True
        opening = self.value.opening
        opening_at = (
            opening.anchor.at
            if isinstance(opening, d.ObservedHistoricalOpening)
            else opening.inception_at
            if isinstance(opening, d.InceptionHistoricalOpening)
            else start
        )
        signatures = []
        for cutoff in (self.cutoff(start), self.cutoff(end)):
            actions = select_actions(
                self.value,
                listing_ids=frozenset(self.instruments),
                start=opening_at,
                through=start,
                cutoff=cutoff,
            )
            signatures.append(
                tuple(
                    (
                        snapshot.series.id,
                        observation.effective_at,
                        observation.kind,
                        observation.state,
                        observation.ratio,
                        observation.amount,
                        observation.currency,
                        observation.target_instrument_id,
                    )
                    for snapshot, index in actions.observations
                    for observation in (snapshot.observations[index],)
                )
            )
        return signatures[0] != signatures[1]

    def activity_complete(
        self,
        start: datetime,
        end: datetime,
        at: datetime,
        *,
        capabilities: tuple[str, ...] = (
            "historical_orders",
            "historical_transactions",
            "historical_dividends",
        ),
    ) -> bool:
        if end <= start:
            return True
        for capability in capabilities:
            intervals = sorted(
                (chunk.start_at, chunk.end_at)
                for chunk in self.value.activity_coverage
                if chunk.capability == capability
                and chunk.coverage_complete
                and chunk.first_observed_at <= self.cutoff(at)
            )
            covered = start
            for left, right in intervals:
                if left > covered:
                    break
                covered = max(covered, right)
                if covered >= end:
                    break
            if covered < end:
                return False
        return True

    def retain(self, use: r.HistoricalSourceUse) -> None:
        if use.use_key in self.uses and self.uses[use.use_key] != use:
            fail_validation(
                "A historical use key cannot change its selection.", field="source_uses"
            )
        self.uses[use.use_key] = use
        if len(self.uses) > d.MAX_HISTORICAL_USES:
            raise DomainError(
                ErrorCode.INPUT_BOUND_EXCEEDED, "Historical source-use capacity exceeded."
            )

    def evidence(
        self,
        identifier: str,
        kind: Literal[
            "mapping",
            "classification",
            "event_revision",
            "opening",
            "calendar",
            "license",
            "action_coverage",
        ],
        at: datetime,
        consumer: r.HistoricalUseConsumer,
        role: r.HistoricalUseRole,
    ) -> None:
        self.retain(
            r.HistoricalEvidenceUse(
                use_key=key(kind, identifier, at, consumer, role),
                role=role,
                use_at=at,
                knowledge_cutoff_at=self.cutoff(at),
                reference_kind=kind,
                reference_id=identifier,
                consumer=consumer,
            )
        )

    def observation(
        self,
        selected: SelectedSource,
        kind: Literal["price", "fx", "corporate_action", "provider_benchmark"],
        at: datetime,
        consumer: r.HistoricalUseConsumer,
        role: r.HistoricalUseRole,
        leg: r.HistoricalConversionLeg | None = None,
    ) -> str:
        use_key = key(
            kind, selected.snapshot_id, selected.observation_index, at, consumer, role, leg
        )
        self.retain(
            r.HistoricalObservationUse(
                use_key=use_key,
                role=role,
                use_at=at,
                knowledge_cutoff_at=self.cutoff(at),
                source_kind=kind,
                snapshot_id=selected.snapshot_id,
                observation_index=selected.observation_index,
                consumer=consumer,
                conversion_leg=leg,
            )
        )
        return use_key

    def missing(
        self,
        expected: r.HistoricalExpectedSeries | r.HistoricalExpectedFx,
        at: datetime,
        calendar: SourceCalendar,
        candidates: tuple[str, ...],
        consumer: r.HistoricalUseConsumer,
        role: r.HistoricalUseRole,
        reason: d.HistoricalReason,
    ) -> None:
        completed = self.calendar_indexes[(calendar.id, calendar.version)].latest(at)
        self.retain(
            r.HistoricalMissingUse(
                use_key=key("missing", expected, at, consumer, role),
                role=role,
                use_at=at,
                knowledge_cutoff_at=self.cutoff(at),
                expected=expected,
                calendar_ref=d.CalendarRef(id=calendar.id, version=calendar.version),
                expected_session=completed.session_date if completed else None,
                reason=reason,
                candidate_snapshot_ids=candidates,
                consumer=consumer,
            )
        )
        self.warnings.add(reason)

    def _anchor(self, calendar: SourceCalendar, at: datetime) -> datetime | None:
        policy = self.value.selection.source_policy
        if policy is None:
            return None
        prepared = self.calendar_indexes[(calendar.id, calendar.version)]
        local_date = at.astimezone(prepared.zone).date()
        # UTC terminal midnight belongs to the completed preceding accounting day.
        if not calendar.period.start <= local_date <= calendar.period.end + timedelta(days=1):
            return None
        latest = prepared.latest(at)
        if latest is None:
            return None
        if at - latest.close_at > timedelta(seconds=policy.max_age_seconds):
            self.warnings.add(d.HistoricalReason.SOURCE_STALE)
            return None
        if latest.session_date != local_date and not policy.allow_closed_session_carry:
            return None
        return latest.close_at

    def _series_snapshots(self, series_id: str) -> tuple[PriceSnapshot | BenchmarkSnapshot, ...]:
        if series_id in self.price_sources:
            return self.price_sources[series_id]
        snapshots: tuple[PriceSnapshot | BenchmarkSnapshot, ...] = tuple(
            item for item in self.value.price_snapshots if item.series.id == series_id
        )
        if self.value.benchmark_input:
            snapshots = tuple(
                {
                    item.id: item
                    for item in (
                        *snapshots,
                        *self.value.benchmark_input.price_snapshots,
                        *self.value.benchmark_input.benchmark_snapshots,
                    )
                    if item.series is not None and item.series.id == series_id
                }.values()
            )
        if len(self.price_sources) < MAX_INDEX_SERIES:
            self.price_sources[series_id] = snapshots
        return snapshots

    def price(
        self,
        series_id: str,
        at: datetime,
        consumer: r.HistoricalUseConsumer,
        role: r.HistoricalUseRole = "holding_valuation",
        *,
        benchmark: bool = False,
    ) -> Decimal | None:
        cache_key = (series_id, at, key(consumer, role, benchmark))
        if cache_key in self.price_cache:
            return self.price_cache[cache_key]
        snapshots = self._series_snapshots(series_id)
        policy = self.value.selection.source_policy
        if not snapshots or snapshots[0].series is None or policy is None:
            self.warnings.add(d.HistoricalReason.PRICE_MISSING)
            self.price_cache[cache_key] = None
            return None
        series = snapshots[0].series
        calendar = self.calendars[(series.calendar_id, series.calendar_version)]
        anchor = self._anchor(calendar, at)
        selected: SelectedSource | None = None
        price: Decimal | None = None
        if anchor is not None:
            if (
                self.window.knowledge_policy is d.KnowledgePolicy.AS_OF_CUTOFF
                and series_id not in self.selection_indexes
                and len(self.selection_indexes) < MAX_INDEX_SERIES
            ):
                # Resolve the original selector's type/subset once, including ID de-duplication.
                kind = (
                    PriceSnapshot if isinstance(snapshots[0], PriceSnapshot) else BenchmarkSnapshot
                )
                typed = tuple(item for item in snapshots if isinstance(item, kind))
                prepared_selection = CalendarSelectionIndex.prepare(
                    typed,
                    series_id=series_id,
                    calendar=self.calendar_indexes[(calendar.id, calendar.version)],
                    policy=policy,
                    cutoff=self.window.source_cutoff_at,
                    budget=self.selection_budget,
                )
                self.selection_indexes[series_id] = prepared_selection
                if prepared_selection is not None:
                    self.selection_budget -= prepared_selection.count
            indexed = self.selection_indexes.get(series_id)
            if indexed is not None:
                _, candidate, reason = indexed.select(anchor)
                if candidate is not None and reason is None:
                    price, selected = candidate.amount, candidate.reference()
            elif isinstance(snapshots[0], PriceSnapshot):
                prices = tuple(item for item in snapshots if isinstance(item, PriceSnapshot))
                selection = select_price(
                    prices,
                    series_id=series_id,
                    at=anchor,
                    source_cutoff_at=self.cutoff(at),
                    policy=policy,
                    calendar=calendar,
                )
                if selection.availability is SourceAvailability.AVAILABLE:
                    price, selected = selection.value, selection.selected
            else:
                levels = tuple(item for item in snapshots if isinstance(item, BenchmarkSnapshot))
                level_selection = select_benchmark(
                    levels,
                    series_id=series_id,
                    at=anchor,
                    source_cutoff_at=self.cutoff(at),
                    policy=policy,
                    calendar=calendar,
                )
                if level_selection.availability is SourceAvailability.AVAILABLE:
                    price, selected = level_selection.level, level_selection.selected
        if selected is not None:
            self.price_effective_cache[cache_key] = selected.effective_at
            self.observation(
                selected,
                "price" if isinstance(snapshots[0], PriceSnapshot) else "provider_benchmark",
                at,
                consumer,
                role,
            )
        else:
            self.missing(
                r.HistoricalExpectedSeries(series_id=series_id),
                at,
                calendar,
                tuple(sorted(item.id for item in snapshots)),
                consumer,
                role,
                d.HistoricalReason.BENCHMARK_GAP if benchmark else d.HistoricalReason.PRICE_MISSING,
            )
        self.price_cache[cache_key] = price
        return price

    def fx(
        self,
        base: CurrencyCode,
        at: datetime,
        consumer: r.HistoricalUseConsumer,
        role: r.HistoricalUseRole = "event_conversion",
        *,
        quote: CurrencyCode | None = None,
    ) -> Decimal | None:
        quote = quote or self.currency
        cache_key = (base, quote, at, key(consumer, role))
        if cache_key in self.fx_cache:
            return self.fx_cache[cache_key]
        conversion_key = key(base, quote, at, consumer, role)
        if base == quote:
            self.conversions[conversion_key] = r.HistoricalConversionUse(
                conversion_key=conversion_key,
                use_at=at,
                base=base,
                quote=quote,
                operation=FxOperation.IDENTITY,
                rate=ONE,
                leg_use_keys=(),
            )
            self.fx_cache[cache_key] = ONE
            return ONE
        self.expected_fx += 1
        policy = self.value.selection.source_policy
        if policy is None:
            self.fx_cache[cache_key] = None
            self.warnings.add(d.HistoricalReason.FX_MISSING)
            return None
        alternatives = []
        for calendar_key in sorted(
            {(item.calendar_id, item.calendar_version) for item in self.value.fx_snapshots}
        ):
            calendar = self.calendars[calendar_key]
            snapshots = tuple(
                item
                for item in self.value.fx_snapshots
                if (item.calendar_id, item.calendar_version) == calendar_key
            )
            anchor = self._anchor(calendar, at)
            if anchor is None:
                continue
            selection = select_fx(
                snapshots,
                base=base,
                quote=quote,
                at=anchor,
                source_cutoff_at=self.cutoff(at),
                policy=policy,
                calendar=calendar,
            )
            if selection.availability is SourceAvailability.AVAILABLE:
                operation_order = {
                    FxOperation.DIRECT: 0,
                    FxOperation.RECIPROCAL: 1,
                    FxOperation.TRIANGULATED: 2,
                    FxOperation.IDENTITY: 0,
                }
                rank = (
                    operation_order[selection.operation],
                    min(
                        policy.provider_priority.index(item.provider_id)
                        for item in selection.sources
                    ),
                    calendar_key,
                )
                alternatives.append((rank, selection))
        if not alternatives:
            for calendar_key in sorted(
                {(item.calendar_id, item.calendar_version) for item in self.value.fx_snapshots}
            ):
                self.missing(
                    r.HistoricalExpectedFx(base=base, quote=quote),
                    at,
                    self.calendars[calendar_key],
                    tuple(
                        sorted(
                            item.id
                            for item in self.value.fx_snapshots
                            if (item.calendar_id, item.calendar_version) == calendar_key
                        )
                    ),
                    consumer,
                    role,
                    d.HistoricalReason.FX_MISSING,
                )
            self.fx_cache[cache_key] = None
            self.warnings.add(d.HistoricalReason.FX_MISSING)
            return None
        selection = min(alternatives, key=lambda item: item[0])[1]
        assert selection.rate is not None
        legs = []
        current = base
        by_id = {item.id: item for item in self.value.fx_snapshots}
        for ordinal, selected in enumerate(selection.sources):
            observation = by_id[selected.snapshot_id].observations[selected.observation_index]
            assert isinstance(observation, FxObservation)
            inverse = observation.base != current
            end = observation.base if inverse else observation.quote
            leg = r.HistoricalConversionLeg(
                conversion_key=conversion_key,
                ordinal=ordinal,
                direction="inverse" if inverse else "direct",
                base=current,
                quote=end,
            )
            legs.append(self.observation(selected, "fx", at, consumer, role, leg))
            current = end
        self.conversions[conversion_key] = r.HistoricalConversionUse(
            conversion_key=conversion_key,
            use_at=at,
            base=base,
            quote=quote,
            operation=selection.operation,
            rate=selection.rate,
            leg_use_keys=tuple(legs),
        )
        self.fx_cache[cache_key] = selection.rate
        self.available_fx += 1
        return selection.rate

    def convert(
        self,
        value: Money | NativeAmount,
        at: datetime,
        consumer: r.HistoricalUseConsumer,
        role: r.HistoricalUseRole = "event_conversion",
    ) -> Decimal | None:
        rate = self.fx(value.currency, at, consumer, role)
        return value.amount * rate if rate is not None else None

    def mapping(self, listing_id: str, at: datetime, *, known_at: datetime | None = None) -> bool:
        instrument = self.instruments[listing_id]
        cutoff = self.cutoff(known_at or at)
        eligible = [
            item
            for item in self.value.mapping_evidence
            if item.listing_id == listing_id
            and item.instrument_id == instrument.instrument_id
            and item.native_currency == instrument.native_currency
            and item.state == "resolved"
            and item.valid_from <= at
            and (item.valid_to is None or at < item.valid_to)
            and item.first_observed_at <= cutoff
        ]
        if not eligible:
            self.warnings.add(d.HistoricalReason.MAPPING_MISSING)
            return False
        chosen = min(eligible, key=lambda item: (item.first_observed_at, item.id))
        self.evidence(
            chosen.id,
            "mapping",
            known_at or at,
            r.HistoricalUseConsumer(
                kind="holding", listing_id=listing_id, instrument_id=instrument.instrument_id
            ),
            "mapping",
        )
        return True

    def opening_known(self, at: datetime) -> bool:
        opening = self.value.opening
        refs = (
            opening.anchor.source_refs
            if isinstance(opening, d.ObservedHistoricalOpening)
            else opening.source_refs
            if isinstance(opening, d.InceptionHistoricalOpening)
            else ()
        )
        return bool(refs) and all(
            item in self.references and self.references[item].first_observed_at <= self.cutoff(at)
            for item in refs
        )

    def state(self, at: datetime, *, after: bool = False) -> State:
        opening = self.value.opening
        events, ambiguous = self.events(at)
        state = State(at, {}, {}, {}, {}, ())
        if isinstance(opening, d.UnavailableHistoricalOpening) or not self.opening_known(at):
            state.quantity_complete = state.cash_complete = state.cost_complete = False
            state.reasons.add(d.HistoricalReason.OPENING_MISSING)
            return state
        if isinstance(opening, d.ObservedHistoricalOpening):
            anchor = opening.anchor
            start = anchor.at
            include_start = anchor.timing == "before_events"
            state.quantities = {item.listing_id: item.quantity for item in anchor.positions}
            state.cash = {item.currency: item.amount for item in anchor.cash}
            state.costs = {
                item.listing_id: NativeAmount(cost.amount, cost.currency)
                if (cost := known(item.acquisition_cost)) is not None
                else None
                for item in anchor.positions
            }
            state.cost_complete = anchor.coverage.complete(d.HistoricalCoverageKey.COST) and all(
                item is not None for item in state.costs.values()
            )
            state.quantity_complete = anchor.coverage.complete(d.HistoricalCoverageKey.QUANTITY)
            state.cash_complete = anchor.coverage.complete(d.HistoricalCoverageKey.CASH)
            if anchor.reconciliation.outcome != "reconciled":
                state.quantity_complete = state.cash_complete = False
                state.reasons.add(d.HistoricalReason.OPENING_UNRECONCILED)
            for ref in anchor.source_refs:
                self.evidence(
                    ref, "opening", at, r.HistoricalUseConsumer(kind="portfolio"), "opening"
                )
        else:
            start, include_start = opening.inception_at, True
        active = tuple(
            item
            for item in events
            if (
                item.identity.economic_at > start
                or (include_start and item.identity.economic_at == start)
            )
            and (item.identity.economic_at < at or (after and item.identity.economic_at == at))
        )
        state.events = active
        if ambiguous or not self.activity_complete(start, at, at):
            state.quantity_complete = state.cash_complete = False
            state.reasons.add(
                d.HistoricalReason.AMBIGUOUS_REVISION
                if ambiguous
                else d.HistoricalReason.EVENT_COVERAGE
            )
        required_listings = frozenset(
            {listing for listing, quantity in state.quantities.items() if quantity != 0}
            | {event.listing_id for event in active if isinstance(event, d.HistoricalExecution)}
        )
        actions = select_actions(
            self.value,
            listing_ids=required_listings,
            start=start,
            through=at,
            cutoff=self.cutoff(at),
        )
        state.actions = actions.observations
        self.action_coverage_checks[at] = actions.complete
        if not actions.complete:
            state.quantity_complete = state.cost_complete = False
            state.reasons.add(d.HistoricalReason.ACTION_COVERAGE)
        for snapshot in actions.coverage_snapshots:
            self.evidence(
                snapshot.id,
                "action_coverage",
                at,
                r.HistoricalUseConsumer(kind="portfolio"),
                "action",
            )
        source_actions: dict[datetime, list[tuple[CorporateActionSnapshot, int]]] = defaultdict(
            list
        )
        for snapshot, index in actions.observations:
            economic_at = snapshot.observations[index].effective_at
            if (economic_at > start or (include_start and economic_at == start)) and (
                economic_at < at or (after and economic_at == at)
            ):
                source_actions[economic_at].append((snapshot, index))
        covered_series = {snapshot.series.id for snapshot in actions.coverage_snapshots}
        grouped: dict[datetime, list[d.HistoricalEvent]] = defaultdict(list)
        for event in active:
            if isinstance(event, d.HistoricalCorporateAction):
                snapshot = next(
                    item for item in self.value.action_snapshots if item.id == event.snapshot_id
                )
                if snapshot.series.id in covered_series:
                    # Retain corroboration while applying the canonical reference action once.
                    self.evidence(
                        event.identity.revision_id,
                        "event_revision",
                        at,
                        r.HistoricalUseConsumer(
                            kind="event", event_revision_id=event.identity.revision_id
                        ),
                        "action",
                    )
                    continue
            grouped[event.identity.economic_at].append(event)
        for instant in sorted(set(grouped) | set(source_actions)):
            batch = grouped[instant]
            for snapshot, index in source_actions[instant]:
                if any(
                    isinstance(event, d.HistoricalExecution)
                    and event.listing_id == snapshot.series.listing_id
                    for event in batch
                ):
                    state.quantity_complete = state.cost_complete = False
                    state.reasons.add(d.HistoricalReason.ACTION_UNSUPPORTED)
                self._apply_action(
                    state,
                    snapshot,
                    index,
                    at,
                    r.HistoricalUseConsumer(
                        kind="holding",
                        listing_id=snapshot.series.listing_id,
                        instrument_id=snapshot.series.instrument_id,
                    ),
                )
            sides: dict[str, set[str]] = defaultdict(set)
            for event in batch:
                if isinstance(event, d.HistoricalExecution):
                    sides[event.listing_id].add(event.side)
            if any(len(side) > 1 for side in sides.values()):
                state.cost_complete = False
            for event in batch:
                self._apply(state, event, at)
            if any(quantity < 0 for quantity in state.quantities.values()):
                state.quantity_complete = state.cost_complete = False
                state.reasons.add(d.HistoricalReason.COST_COVERAGE)
        self.warnings.update(state.reasons)
        return state

    def _apply(self, state: State, event: d.HistoricalEvent, known_at: datetime) -> None:
        identity = event.identity
        consumer = r.HistoricalUseConsumer(kind="event", event_revision_id=identity.revision_id)
        self.evidence(
            identity.revision_id, "event_revision", known_at, consumer, "event_conversion"
        )
        native = event_money(event)
        if native is not None:
            state.cash[native.currency] = state.cash.get(native.currency, ZERO) + native.amount
        if isinstance(event, d.HistoricalExecution):
            if not self.mapping(event.listing_id, identity.economic_at, known_at=known_at):
                state.quantity_complete = state.cost_complete = False
            old_quantity = state.quantities.get(event.listing_id, ZERO)
            fees, taxes = known(event.fees), known(event.taxes)
            cost = state.costs.get(
                event.listing_id,
                NativeAmount(ZERO, event.native_price.currency) if old_quantity == 0 else None,
            )
            if (
                fees is None
                or taxes is None
                or cost is None
                or any(
                    item.currency != event.native_price.currency
                    for item in (event.gross_value, fees, taxes, cost)
                )
            ):
                state.costs[event.listing_id] = None
                state.cost_complete = False
            elif event.side == "buy":
                state.costs[event.listing_id] = NativeAmount(
                    cost.amount + event.gross_value.amount + fees.amount + taxes.amount,
                    cost.currency,
                )
            elif old_quantity >= event.quantity and old_quantity > 0:
                disposed = cost.amount * event.quantity / old_quantity
                state.costs[event.listing_id] = NativeAmount(cost.amount - disposed, cost.currency)
                gain = event.gross_value.amount - fees.amount - taxes.amount - disposed
                reporting = self.convert(
                    NativeAmount(gain, cost.currency), identity.economic_at, consumer
                )
                if reporting is None:
                    state.cost_complete = False
                else:
                    state.realized[event.listing_id] = (
                        state.realized.get(event.listing_id, ZERO) + reporting
                    )
            else:
                state.cost_complete = False
            state.quantities[event.listing_id] = old_quantity + (
                event.quantity if event.side == "buy" else -event.quantity
            )
        elif isinstance(event, d.HistoricalCorporateAction):
            snapshot = next(
                item for item in self.value.action_snapshots if item.id == event.snapshot_id
            )
            self._apply_action(state, snapshot, event.observation_index, known_at, consumer)
        elif isinstance(event, d.HistoricalUnknownActivity):
            state.reasons.add(d.HistoricalReason.UNKNOWN_EVENT)
            if d.HistoricalCoverageKey.QUANTITY in event.affected_coverage:
                state.quantity_complete = False
            if d.HistoricalCoverageKey.CASH in event.affected_coverage:
                state.cash_complete = False
            state.cost_complete = False

    def _apply_action(
        self,
        state: State,
        snapshot: CorporateActionSnapshot,
        index: int,
        known_at: datetime,
        consumer: r.HistoricalUseConsumer,
    ) -> None:
        observation = snapshot.observations[index]
        if snapshot.provenance.first_observed_at > self.cutoff(
            known_at
        ) or snapshot.provenance.effective_at > self.cutoff(known_at):
            state.quantity_complete = state.cost_complete = False
            state.reasons.add(d.HistoricalReason.ACTION_COVERAGE)
            return
        selected = SelectedSource(
            snapshot_id=snapshot.id,
            content_digest=source_snapshot_digest(snapshot),
            provider_id=snapshot.provenance.provider_id,
            license_version_id=snapshot.provenance.license_version_id,
            observation_index=index,
            effective_at=observation.effective_at,
            first_observed_at=snapshot.provenance.first_observed_at,
        )
        self.observation(selected, "corporate_action", known_at, consumer, "action")
        listing = snapshot.series.listing_id
        if (
            observation.kind is CorporateActionKind.SPLIT
            and observation.state is ObservationState.AVAILABLE
            and observation.ratio is not None
            and listing is not None
        ):
            state.quantities[listing] = state.quantities.get(listing, ZERO) * observation.ratio
        elif observation.kind is not CorporateActionKind.CASH_DISTRIBUTION:
            state.quantity_complete = state.cost_complete = False
            state.reasons.add(d.HistoricalReason.ACTION_UNSUPPORTED)
        # Cash-distribution reference facts do not synthesize broker account receipts.

    def valuation(self, at: datetime, *, after: bool = False) -> Valuation:
        if (at, after) in self.valuation_cache:
            return self.valuation_cache[(at, after)]
        state = self.state(at, after=after)
        holdings: dict[str, Decimal | None] = {}
        prices: dict[str, Decimal | None] = {}
        rates: dict[CurrencyCode, Decimal | None] = {}
        cash_values: dict[CurrencyCode, Decimal | None] = {}
        exact = False
        matching_anchors = [
            item
            for item in self.value.valuation_anchors
            if item.at == at
            and item.timing == ("after_events" if after else "before_events")
            and item.exact_economic_valuation
            and item.reconciliation.outcome == "reconciled"
            and all(
                ref in self.references and self.references[ref].first_observed_at <= self.cutoff(at)
                for ref in item.source_refs
            )
        ]
        anchor = min(matching_anchors, key=lambda item: item.id) if matching_anchors else None
        if anchor is not None and (
            {item.listing_id: item.quantity for item in anchor.positions}
            != {
                listing: quantity for listing, quantity in state.quantities.items() if quantity != 0
            }
            or {item.currency: item.amount for item in anchor.cash if item.amount != 0}
            != {currency: cash for currency, cash in state.cash.items() if cash != 0}
        ):
            anchor = None
            self.warnings.add(d.HistoricalReason.OPENING_UNRECONCILED)
        anchor_positions = {item.listing_id: item for item in anchor.positions} if anchor else {}
        if anchor:
            exact = True
        for listing, quantity in sorted(state.quantities.items()):
            if quantity == 0:
                continue
            self._cell(f"{listing}:{after}", at)
            instrument = self.instruments[listing]
            consumer = r.HistoricalUseConsumer(
                kind="holding", listing_id=listing, instrument_id=instrument.instrument_id
            )
            rate = self.fx(instrument.native_currency, at, consumer, "holding_valuation")
            rates[instrument.native_currency] = rate
            candidates = [
                item
                for item in self.value.price_snapshots
                if item.series.id in instrument.source_series_ids
                and item.series.basis is PriceBasis.RAW_CLOSE
                and item.series.currency == instrument.native_currency
            ]
            priority = (
                self.value.selection.source_policy.provider_priority
                if self.value.selection.source_policy
                else ()
            )
            candidates.sort(
                key=lambda item: (
                    priority.index(item.provenance.provider_id)
                    if item.provenance.provider_id in priority
                    else 999,
                    item.series.id,
                    item.id,
                )
            )
            price = None
            if instrument.quantity_basis is not PriceBasis.RAW_CLOSE or (
                not candidates
                and any(
                    item.series.id in instrument.source_series_ids
                    and item.series.basis is not PriceBasis.RAW_CLOSE
                    for item in self.value.price_snapshots
                )
            ):
                self.warnings.add(d.HistoricalReason.UNSUPPORTED_BASIS)
            if instrument.quantity_basis is PriceBasis.RAW_CLOSE and self.mapping(listing, at):
                for series_id in dict.fromkeys(item.series.id for item in candidates):
                    price = self.price(series_id, at, consumer)
                    if price is not None or any(
                        item.series.id == series_id
                        and item.provenance.first_observed_at <= self.cutoff(at)
                        and item.provenance.effective_at <= self.cutoff(at)
                        for item in candidates
                    ):
                        break
            if price is not None:
                quote_at = self.price_effective_cache.get(
                    (series_id, at, key(consumer, "holding_valuation", False))
                )
                if quote_at is not None:
                    for snapshot, index in state.actions:
                        action = snapshot.observations[index]
                        if (
                            snapshot.series.listing_id != listing
                            or action.kind is not CorporateActionKind.SPLIT
                        ):
                            continue
                        applied_to_state = action.effective_at < at or (
                            after and action.effective_at == at
                        )
                        applied_to_quote = action.effective_at <= quote_at
                        if applied_to_state == applied_to_quote:
                            continue
                        if action.ratio is None or action.state is not ObservationState.AVAILABLE:
                            price = None
                            break
                        # A split changes units, not economic wealth. Convert the
                        # raw-close quote into the exact units of this quantity.
                        price = price / action.ratio if applied_to_state else price * action.ratio
            prices[listing] = price
            market = quantity * price * rate if price is not None and rate is not None else None
            if (
                listing in anchor_positions
                and (anchor_money := known(anchor_positions[listing].market_value)) is not None
            ):
                market = self.convert(anchor_money, at, consumer, "attribution_boundary")
            holdings[listing] = market
            if market is not None:
                self.successful_cells.add((f"{listing}:{after}", at))
        for currency, cash in sorted(state.cash.items(), key=lambda item: str(item[0])):
            self._cell(f"{currency}:{after}", at)
            rate = self.fx(currency, at, r.HistoricalUseConsumer(kind="cash"), "cash_valuation")
            rates[currency] = rate
            cash_values[currency] = cash * rate if rate is not None else None
            if cash_values[currency] is not None:
                self.successful_cells.add((f"{currency}:{after}", at))
        invested_missing = not state.quantity_complete or any(
            item is None for item in holdings.values()
        )
        cash_missing = not state.cash_complete or any(item is None for item in cash_values.values())
        degraded = self.window.coverage_policy is CoveragePolicy.ALLOW_DEGRADED
        invested = (
            sum((item for item in holdings.values() if item is not None), ZERO)
            if not invested_missing or degraded
            else None
        )
        cash_total = (
            sum((item for item in cash_values.values() if item is not None), ZERO)
            if not cash_missing or degraded
            else None
        )
        total = invested + cash_total if invested is not None and cash_total is not None else None
        result = Valuation(
            at,
            state,
            holdings,
            prices,
            rates,
            cash_values,
            invested,
            cash_total,
            total,
            invested_missing or cash_missing,
            exact,
        )
        self.valuation_cache[(at, after)] = result
        return result

    def _cell(self, identity: str, at: datetime) -> None:
        cell = (identity, at)
        if cell not in self.cells:
            self.cells.add(cell)
            self.expected_cells += 1
            if len(self.cells) > d.MAX_HISTORICAL_CELLS:
                raise DomainError(
                    ErrorCode.INPUT_BOUND_EXCEEDED, "Historical valuation-cell capacity exceeded."
                )

    def context(
        self, name: str, *, available: bool = True, partial: bool = False
    ) -> r.HistoricalResultContext:
        warnings = list(self.value.warnings)
        restated = self.window.knowledge_policy is d.KnowledgePolicy.AS_OF_CUTOFF and any(
            item.first_observed_at > item.effective_at for item in self.value.sources
        )
        if restated:
            self.warnings.add(d.HistoricalReason.RESTATED)
        assumptions: list[
            Literal[
                "utc_accounting_boundaries",
                "previous_completed_session_close",
                "explicit_target_comparison",
                "price_only_benchmark",
                "act_365",
                "income_holdings_and_fx_may_change",
            ]
        ] = ["utc_accounting_boundaries", "previous_completed_session_close", "act_365"]
        if (
            self.value.target_grouping
            and self.value.target_grouping.policy == "explicit_comparison"
        ):
            assumptions.append("explicit_target_comparison")
            self.warnings.add(d.HistoricalReason.TARGET_COMPARISON)
        warnings.extend(d.HistoricalIssue(reason_code=item) for item in sorted(self.warnings))
        warnings = sorted(set(warnings), key=lambda item: (item.reason_code, item.reference_ids))
        measures = {item.key: item for item in self.value.coverage.measures}
        for measure_key, expected, actual, reason in (
            (
                d.HistoricalCoverageKey.ACTIONS,
                len(self.action_coverage_checks),
                sum(self.action_coverage_checks.values()),
                d.HistoricalReason.ACTION_COVERAGE,
            ),
            (
                d.HistoricalCoverageKey.VALUATIONS,
                self.expected_cells,
                len(self.successful_cells),
                d.HistoricalReason.VALUATION_MISSING,
            ),
            (
                d.HistoricalCoverageKey.FX,
                self.expected_fx,
                self.available_fx,
                d.HistoricalReason.FX_MISSING,
            ),
        ):
            measures[measure_key] = d.HistoricalCoverageMeasure(
                key=measure_key,
                expected_count=expected,
                available_count=actual,
                complete=actual == expected,
                reasons=() if actual == expected else (reason,),
            )
        return r.HistoricalResultContext(
            account_id=self.value.account_id,
            window=self.window,
            method=r.HistoricalMethod(name=name, version=d.HISTORICAL_METHOD_VERSION),
            primitive_methods=tuple(
                r.HistoricalMethod(name=method, version=version)
                for method, version in sorted(self.primitive_methods)
            ),
            input_digest=historical_input_digest(self.value),
            source_policy_version=self.value.selection.source_policy.version
            if self.value.selection.source_policy
            else None,
            accounting_policy_version=self.value.selection.accounting_policy.version,
            coverage=d.HistoricalCoverage(
                measures=tuple(measures[key] for key in sorted(measures))
            ),
            quality=QualityState.PARTIAL
            if not available
            else QualityState.PARTIAL
            if partial
            else QualityState.FRESH,
            availability=d.HistoricalAvailability.UNAVAILABLE
            if not available
            else d.HistoricalAvailability.PARTIAL
            if partial
            else d.HistoricalAvailability.AVAILABLE,
            reconstruction="restated" if restated else "point_in_time",
            sources=tuple(sorted(self.value.sources, key=lambda item: (item.kind, item.id))),
            warnings=tuple(warnings),
            assumptions=tuple(assumptions),
        )

    def ordered_uses(self) -> tuple[r.HistoricalSourceUse, ...]:
        return tuple(self.uses[item] for item in sorted(self.uses))

    def ordered_conversions(self) -> tuple[r.HistoricalConversionUse, ...]:
        return tuple(self.conversions[item] for item in sorted(self.conversions))


def event_money(event: d.HistoricalEvent) -> Money | None:
    if isinstance(event, (d.HistoricalExternalFlow, d.HistoricalCashEffect)):
        return event.signed_amount
    if isinstance(event, d.HistoricalExecution):
        return event.cash_impact
    if isinstance(event, d.HistoricalDividend):
        return event.net
    return event.known_amount if isinstance(event, d.HistoricalUnknownActivity) else None


def event_kind(event: d.HistoricalEvent) -> d.HistoricalCashFlowKind:
    if isinstance(event, d.HistoricalExecution):
        return d.HistoricalCashFlowKind(event.side)
    if isinstance(event, d.HistoricalCashEffect):
        return d.HistoricalCashFlowKind(event.effect_kind)
    return d.HistoricalCashFlowKind(event.kind)


def period_bounds(at: datetime, frequency: d.HistoricalFrequency) -> tuple[date, date]:
    day = at.date()
    if frequency is d.HistoricalFrequency.DAILY:
        return day, day
    first = day.replace(day=1)
    next_month = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first, next_month - timedelta(days=1)


def midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, UTC)
