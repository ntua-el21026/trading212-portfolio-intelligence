"""Cross-record invariants for sealed historical inputs; no source lookups or clocks."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, localcontext

from . import historical as d
from .errors import fail_validation
from .historical_serialization import historical_canonical_bytes
from .source_details import CorporateActionSnapshot
from .sources import BenchmarkSnapshot, PriceSnapshot
from .values import require_bounded_text


def validate_historical_input(value: d.HistoricalInput) -> d.HistoricalInput:
    if not isinstance(value, d.HistoricalInput):
        fail_validation("A typed historical input is required.", field="input")
    references = {item.id for item in value.sources}
    listings = {item.listing_id: item for item in value.instruments}
    mappings = {item.id: item for item in value.mapping_evidence}
    events = {item.identity.revision_id: item for item in value.event_candidates}
    calendars = {(item.id, item.version) for item in value.calendars}
    actions = {item.id: item for item in value.action_snapshots}

    def refs(items: tuple[str, ...]) -> None:
        if not set(items) <= references:
            fail_validation("Historical evidence reference is not captured.", field="sources")

    anchors = list(value.valuation_anchors)
    if isinstance(value.opening, d.ObservedHistoricalOpening):
        anchors.append(value.opening.anchor)
        if value.opening.anchor.at > value.selection.window.start_at:
            fail_validation("An opening cannot follow the requested window.", field="opening")
    elif isinstance(value.opening, d.InceptionHistoricalOpening):
        refs(value.opening.source_refs)
        if value.opening.inception_at > value.selection.window.start_at:
            fail_validation("Inception follows the requested window.", field="opening")
    anchor_ids: dict[str, d.HistoricalValuationAnchor] = {}
    for anchor in anchors:
        if anchor.id in anchor_ids and anchor_ids[anchor.id] != anchor:
            fail_validation("An immutable anchor identity cannot change.", field="anchors")
        anchor_ids[anchor.id] = anchor
        refs(anchor.source_refs)
        refs(anchor.reconciliation.anchor_refs)
        validate_reconciliation(anchor.reconciliation)
        for position in anchor.positions:
            if position.listing_id not in listings or (
                listings[position.listing_id].instrument_id != position.instrument_id
            ):
                fail_validation(
                    "Anchor listing identity differs from inventory.", field="positions"
                )
    for chunk in value.activity_coverage:
        refs((chunk.ingestion_run_id,))
    if len({chunk.id for chunk in value.activity_coverage}) != len(value.activity_coverage):
        fail_validation("Activity coverage identities must be unique.", field="activity_coverage")
    for mapping in value.mapping_evidence:
        refs((mapping.source_ref,))
        if mapping.listing_id in listings:
            instrument = listings[mapping.listing_id]
            if mapping.state == "resolved" and (
                instrument.instrument_id != mapping.instrument_id
                or instrument.native_currency != mapping.native_currency
            ):
                fail_validation("Captured resolved mapping changes identity.", field="mapping")
    for item in value.classification_evidence:
        refs(item.source_refs)
        refs((item.license_version_id,))
    for event in value.event_candidates:
        identity = event.identity
        refs((identity.source_record_id,))
        if identity.source_occurrence_id is not None:
            refs((identity.source_occurrence_id,))
        prior = identity.supersedes_revision_id
        if prior is not None:
            if prior not in events or events[prior].identity.economic_key != identity.economic_key:
                fail_validation(
                    "Economic supersession must stay within its captured key.", field="events"
                )
            visited = {identity.revision_id}
            while prior is not None:
                if prior in visited:
                    fail_validation("Economic revision chain contains a cycle.", field="events")
                visited.add(prior)
                prior = events[prior].identity.supersedes_revision_id
        if isinstance(event, d.HistoricalExecution):
            event_instrument = listings.get(event.listing_id)
            if event_instrument is None or event_instrument.instrument_id != event.instrument_id:
                fail_validation("Execution listing identity is not captured.", field="events")
            if event.mapping_id not in mappings:
                fail_validation("Execution mapping evidence is not captured.", field="mapping_id")
            if event.native_price.currency != event_instrument.native_currency:
                fail_validation("Execution native price currency differs.", field="native_price")
            if event.explicit_fx_source_ref is not None:
                refs((event.explicit_fx_source_ref,))
        elif isinstance(event, d.HistoricalCorporateAction):
            snapshot = actions.get(event.snapshot_id)
            if snapshot is None or event.observation_index >= len(snapshot.observations):
                fail_validation("Action observation is not captured.", field="observation_index")
            if snapshot.observations[event.observation_index].effective_at != identity.economic_at:
                fail_validation(
                    "Action economic time differs from its observation.", field="events"
                )
            refs(event.account_effect_evidence)
    snapshots: list[PriceSnapshot | CorporateActionSnapshot] = [
        *value.price_snapshots,
        *value.action_snapshots,
    ]
    for source_snapshot in snapshots:
        if (
            source_snapshot.series.calendar_id,
            source_snapshot.series.calendar_version,
        ) not in calendars:
            fail_validation("Source calendar is not captured.", field="calendars")
    for fx in value.fx_snapshots:
        if (fx.calendar_id, fx.calendar_version) not in calendars:
            fail_validation("FX calendar is not captured.", field="calendars")
    benchmark = value.benchmark_input
    if benchmark is not None:
        if value.selection.benchmark_version_id != benchmark.benchmark_version_id:
            fail_validation("Selected benchmark differs from captured version.", field="benchmark")
        if (benchmark.content.calendar_id, benchmark.content.calendar_version) not in calendars:
            fail_validation("Benchmark calendar is not captured.", field="calendars")
        benchmark_sources: tuple[PriceSnapshot | BenchmarkSnapshot, ...] = (
            *benchmark.price_snapshots,
            *benchmark.benchmark_snapshots,
        )
        for source in benchmark_sources:
            if (
                source.series is not None
                and (source.series.calendar_id, source.series.calendar_version) not in calendars
            ):
                fail_validation("Benchmark component calendar is not captured.", field="calendars")
    grouping = value.target_grouping
    if grouping is not None and (
        grouping.version_id != value.selection.target_version_id
        or grouping.policy != value.selection.grouping_policy
    ):
        fail_validation("Target grouping differs from selected immutable scope.", field="target")
    historical_canonical_bytes(value)
    return value


def validate_reconciliation(proof: d.HistoricalReconciliationProof) -> None:
    """Recompute every supplied residual; a label alone cannot prove reconciliation."""
    identities = [(line.kind, line.identity, line.currency) for line in proof.lines]
    if len(set(identities)) != len(identities):
        fail_validation("Reconciliation lines must be disjoint.", field="reconciliation")
    with localcontext(Context(prec=80, rounding=ROUND_HALF_EVEN)):
        for line in proof.lines:
            if line.expected is None or line.observed is None:
                if line.state != "unavailable" or line.residual is not None:
                    fail_validation(
                        "Unknown reconciliation cannot claim a residual.", field="reconciliation"
                    )
                continue
            actual = line.observed - line.expected
            if line.residual != actual:
                fail_validation(
                    "Reconciliation residual does not match inputs.", field="reconciliation"
                )
            expected_state = "reconciled" if abs(actual) <= line.tolerance else "unreconciled"
            if line.state != expected_state:
                fail_validation(
                    "Reconciliation state does not match residual.", field="reconciliation"
                )
    actual_outcome = (
        "unreconciled"
        if any(line.state == "unreconciled" for line in proof.lines)
        else "unavailable"
        if not proof.lines or any(line.state == "unavailable" for line in proof.lines)
        else "reconciled"
    )
    if proof.outcome != actual_outcome:
        fail_validation("Reconciliation outcome does not match its proof.", field="reconciliation")


def validate_group_name(name: str) -> None:
    require_bounded_text(name, field="group_name", maximum=160)
