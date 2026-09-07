"""Bound-before-materialization immutable historical candidate capture."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from trading212_application import historical as app
from trading212_domain import historical as d
from trading212_domain.historical_serialization import (
    canonical_historical_input,
    historical_input_digest,
    historical_input_from_json,
)
from trading212_domain.source_details import CorporateActionSnapshot
from trading212_domain.sources import (
    BenchmarkSnapshot,
    FxSnapshot,
    PriceSnapshot,
    SourceUse,
)
from trading212_domain.values import CurrencyCode
from trading212_security.principals import Principal, Scope

from . import historical_models as hm
from . import models as lm
from . import source_models as sm
from .historical_base import digest, encoded, error
from .historical_evidence import HistoricalEvidenceRegistrationStore
from .historical_normalization import normalize_record
from .target_models import (
    TargetHoldingModel,
    TargetNodeModel,
    TargetVersionModel,
    VirtualPortfolioModel,
)


class HistoricalCaptureStore(HistoricalEvidenceRegistrationStore):
    def _capture_view(
        self, session: Session, owner: UUID, row: hm.HistoricalInputModel
    ) -> app.HistoricalCaptureView:
        self._account(session, owner, row.broker_account_id)
        self._reauthorize(session, owner, row.broker_account_id, input_id=row.id)
        value = historical_input_from_json(row.canonical_input)
        if (
            not row.sealed
            or value.owner_id != str(owner)
            or value.account_id != str(row.broker_account_id)
            or historical_input_digest(value) != row.input_digest
        ):
            raise error("HISTORICAL_UNAVAILABLE")
        return app.HistoricalCaptureView(
            id=str(row.id), input_digest=row.input_digest, captured_at=row.created_at, input=value
        )

    async def load(self, principal: Principal, capture_id: str) -> app.HistoricalCaptureView:
        def operation(
            session: Session, owner: UUID, account: UUID | None
        ) -> app.HistoricalCaptureView:
            row = self._owned(session, owner, hm.HistoricalInputModel, capture_id)
            if row.target_version_id is not None:
                self._authorizer.require_scope(principal, Scope.TARGETS_READ, now=self._now())
            return self._capture_view(session, owner, row)

        return await self._run(principal, None, operation)

    async def capture(
        self, principal: Principal, account_id: str, *, request: d.HistoricalSelectionRequest
    ) -> app.HistoricalCaptureView:
        def operation(
            session: Session, owner: UUID, account: UUID | None
        ) -> app.HistoricalCaptureView:
            assert account is not None
            return self._capture(session, principal, owner, account, request)

        return await self._run(principal, account_id, operation)

    def _policy(
        self, session: Session, owner: UUID, account: UUID, cutoff: object
    ) -> hm.HistoricalPolicyModel | None:
        rows = session.scalars(
            select(hm.HistoricalPolicyModel)
            .where(
                hm.HistoricalPolicyModel.owner_id == owner,
                hm.HistoricalPolicyModel.broker_account_id == account,
                hm.HistoricalPolicyModel.first_observed_at <= cutoff,
                hm.HistoricalPolicyModel.effective_at <= cutoff,
            )
            .order_by(
                hm.HistoricalPolicyModel.effective_at.desc(),
                hm.HistoricalPolicyModel.first_observed_at.desc(),
            )
            .limit(2)
        ).all()
        if (
            len(rows) == 2
            and rows[0].effective_at == rows[1].effective_at
            and rows[0].content_digest != rows[1].content_digest
        ):
            raise error("VALIDATION_FAILED")
        return rows[0] if rows else None

    def _capture(
        self,
        session: Session,
        principal: Principal,
        owner: UUID,
        account: UUID,
        request: d.HistoricalSelectionRequest,
    ) -> app.HistoricalCaptureView:
        window = request.window
        if window.source_cutoff_at > self._now() or window.end_at > self._now():
            raise error("VALIDATION_FAILED")
        policy_row = self._policy(session, owner, account, window.source_cutoff_at)
        policy = None if policy_row is None else self._policy_view(policy_row).registration
        if policy is None:
            if request.source_policy is not None or request.reporting_calendar_ref is not None:
                raise error("INPUT_SNAPSHOT_MISMATCH")
        elif (request.accounting_policy, request.source_policy, request.reporting_calendar_ref) != (
            policy.accounting_policy,
            policy.source_policy,
            policy.reporting_calendar_ref,
        ):
            raise error("INPUT_SNAPSHOT_MISMATCH")
        references: dict[tuple[str, str], d.HistoricalSourceReference] = {}

        def reference(kind: str, identifier: UUID | str) -> d.HistoricalSourceReference:
            value = self._reference(session, owner, account, kind, identifier)
            references[(value.kind, value.id)] = value
            if len(references) > d.MAX_HISTORICAL_SOURCES:
                raise error("RESULT_TOO_LARGE")
            return value

        evidence_rows = session.scalars(
            select(hm.HistoricalEvidenceModel)
            .where(
                hm.HistoricalEvidenceModel.owner_id == owner,
                hm.HistoricalEvidenceModel.broker_account_id == account,
                hm.HistoricalEvidenceModel.first_observed_at <= window.source_cutoff_at,
            )
            .order_by(hm.HistoricalEvidenceModel.first_observed_at, hm.HistoricalEvidenceModel.id)
            .limit(257)
        ).all()
        if len(evidence_rows) > 256:
            raise error("RESULT_TOO_LARGE")
        evidence = []
        for evidence_row in evidence_rows:
            self._reauthorize(session, owner, account, evidence_id=evidence_row.id)
            reference("historical_evidence", evidence_row.id)
            evidence.append((evidence_row, self._evidence_view(evidence_row).registration))
        activity_coverage = tuple(
            d.HistoricalActivityCoverage(
                id=chunk.id,
                ingestion_run_id=chunk.ingestion_run_id,
                capability=chunk.capability,
                start_at=chunk.start_at,
                end_at=chunk.end_at,
                first_observed_at=evidence_row.first_observed_at,
                coverage_complete=chunk.coverage_complete,
            )
            for evidence_row, value in evidence
            for chunk in value.activity_coverage
        )
        if len(activity_coverage) > 10000:
            raise error("RESULT_TOO_LARGE")
        for chunk in activity_coverage:
            reference("ingestion_run", chunk.ingestion_run_id)
        anchors = {x.id: x for _, value in evidence for x in value.valuation_anchors}
        openings: list[
            tuple[datetime, datetime, d.ObservedHistoricalOpening | d.InceptionHistoricalOpening]
        ] = []
        for evidence_row, evidence_value in evidence:
            if isinstance(evidence_value.opening, d.ObservedHistoricalOpening):
                candidate = evidence_value.opening
                if candidate.anchor.at <= min(
                    [
                        window.start_at,
                        *[
                            x.start_at
                            for x in request.support_windows
                            if x.reason != "previous_calendar_income"
                        ],
                    ]
                ):
                    openings.append(
                        (candidate.anchor.at, evidence_row.first_observed_at, candidate)
                    )
                anchors[candidate.anchor.id] = candidate.anchor
            elif (
                isinstance(evidence_value.opening, d.InceptionHistoricalOpening)
                and evidence_value.opening.inception_at <= window.start_at
            ):
                openings.append(
                    (
                        evidence_value.opening.inception_at,
                        evidence_row.first_observed_at,
                        evidence_value.opening,
                    )
                )
        openings.sort(key=lambda x: (x[0], x[1]))
        opening: d.HistoricalOpening = (
            openings[-1][2]
            if openings
            else d.UnavailableHistoricalOpening(reasons=(d.HistoricalReason.OPENING_MISSING,))
        )
        if len(anchors) > 10000:
            raise error("RESULT_TOO_LARGE")
        classifications = tuple(x for _, value in evidence for x in value.classifications)
        if len(classifications) > 8192:
            raise error("RESULT_TOO_LARGE")
        for classification in classifications:
            reference("classification_evidence", classification.id)
            for identifier in (*classification.source_refs, classification.license_version_id):
                found = self._find_reference(session, owner, account, identifier)
                references[(found.kind, found.id)] = found
        for anchor in anchors.values():
            for identifier in (*anchor.source_refs, *anchor.reconciliation.anchor_refs):
                found = self._find_reference(session, owner, account, identifier)
                references[(found.kind, found.id)] = found
        price_ids = set(() if policy is None else policy.price_series_ids)
        action_ids = set(() if policy is None else policy.action_series_ids)
        benchmark_version = None
        if request.benchmark_version_id is not None:
            benchmark_version = self._sources._benchmark_version(
                session, owner, UUID(request.benchmark_version_id)
            )
            if benchmark_version.published_at > window.source_cutoff_at:
                raise error("VALIDATION_FAILED")
            reference("benchmark_version", request.benchmark_version_id)
        benchmark_series = set(
            ()
            if benchmark_version is None
            else (x.source_id for x in benchmark_version.content.components)
        )
        series_rows = session.scalars(
            select(sm.MarketSourceSeriesModel)
            .where(
                sm.MarketSourceSeriesModel.owner_id == owner,
                sm.MarketSourceSeriesModel.id.in_(
                    [UUID(x) for x in price_ids | action_ids | benchmark_series]
                ),
            )
            .limit(513)
        ).all()
        if len(series_rows) > 512 or len(series_rows) != len(
            price_ids | action_ids | benchmark_series
        ):
            raise error("NOT_FOUND")
        for series_row in series_rows:
            self._sources._permit(session, owner, series_row.license_version_id, SourceUse.DISPLAY)
            reference("provider_license_version", series_row.license_version_id)
        mapping_ids = {x.mapping_id for x in series_rows if x.mapping_id is not None}
        series_instruments = {x.instrument_id for x in series_rows if x.instrument_id is not None}
        mapping_rows = session.scalars(
            select(sm.MarketDataInstrumentModel)
            .where(
                sm.MarketDataInstrumentModel.owner_id == owner,
                or_(
                    sm.MarketDataInstrumentModel.id.in_(mapping_ids),
                    sm.MarketDataInstrumentModel.instrument_id.in_(series_instruments),
                ),
                sm.MarketDataInstrumentModel.created_at <= window.source_cutoff_at,
            )
            .limit(8193)
        ).all()
        if len(mapping_rows) > 8192:
            raise error("RESULT_TOO_LARGE")
        mappings = []
        for mapping_row in mapping_rows:
            if mapping_row.instrument_id is None:
                continue
            source = reference("instrument_mapping", mapping_row.id)
            mappings.append(
                d.HistoricalMappingEvidence(
                    id=str(mapping_row.id),
                    source_ref=source.id,
                    instrument_id=str(mapping_row.instrument_id),
                    listing_id=None
                    if mapping_row.listing_id is None
                    else str(mapping_row.listing_id),
                    native_currency=CurrencyCode(mapping_row.currency),
                    asset_type=mapping_row.asset_type,
                    valid_from=mapping_row.valid_from,
                    valid_to=mapping_row.valid_to,
                    first_observed_at=mapping_row.created_at,
                    state=cast(Literal["resolved", "unresolved", "ambiguous"], mapping_row.state),
                )
            )
        records = session.scalars(
            select(lm.SourceRecordModel)
            .where(
                lm.SourceRecordModel.broker_account_id == account,
                lm.SourceRecordModel.observed_at <= window.source_cutoff_at,
                lm.SourceRecordModel.capability.in_(
                    ("historical_orders", "historical_dividends", "historical_transactions")
                ),
            )
            .order_by(lm.SourceRecordModel.observed_at, lm.SourceRecordModel.id)
            .limit(10001)
        ).all()
        if len(records) > 10000:
            raise error("RESULT_TOO_LARGE")
        occurrences = {
            x.source_record_id: x
            for x in session.scalars(
                select(lm.SourceRecordOccurrenceModel)
                .where(
                    lm.SourceRecordOccurrenceModel.source_record_id.in_([x.id for x in records]),
                    lm.SourceRecordOccurrenceModel.observed_at <= window.source_cutoff_at,
                )
                .distinct(lm.SourceRecordOccurrenceModel.source_record_id)
                .order_by(
                    lm.SourceRecordOccurrenceModel.source_record_id,
                    lm.SourceRecordOccurrenceModel.observed_at,
                    lm.SourceRecordOccurrenceModel.id,
                )
                .limit(10001)
            )
        }
        events = []
        for source_record in records:
            event = normalize_record(
                source_record, occurrences.get(source_record.id), tuple(mapping_rows)
            )
            if event is None or event.identity.economic_at >= window.end_at:
                continue
            events.append(event)
            raw = reference("broker_source_record", source_record.id)
            references[(raw.kind, raw.id)] = replace(
                raw,
                effective_at=event.identity.economic_at,
                derived_projection_digest=digest(event),
            )
            if source_record.id in occurrences:
                reference("broker_source_occurrence", occurrences[source_record.id].id)
        instruments: dict[str, d.HistoricalInstrument] = {}
        for series_row in series_rows:
            if (
                series_row.listing_id is not None
                and series_row.instrument_id is not None
                and str(series_row.id) in price_ids
            ):
                prior_instrument = instruments.get(str(series_row.listing_id))
                identifiers = (
                    *(() if prior_instrument is None else prior_instrument.source_series_ids),
                    str(series_row.id),
                )
                instruments[str(series_row.listing_id)] = d.HistoricalInstrument(
                    listing_id=str(series_row.listing_id),
                    instrument_id=str(series_row.instrument_id),
                    native_currency=CurrencyCode(series_row.currency),
                    source_series_ids=tuple(sorted(identifiers)),
                )
        for anchor in anchors.values():
            for position in anchor.positions:
                if position.listing_id not in instruments:
                    listing = session.get(lm.ListingModel, UUID(position.listing_id))
                    assert listing is not None
                    instruments[position.listing_id] = d.HistoricalInstrument(
                        listing_id=position.listing_id,
                        instrument_id=position.instrument_id,
                        native_currency=CurrencyCode(listing.trading_currency),
                    )
        if len(instruments) > 256:
            raise error("RESULT_TOO_LARGE")
        start = min(
            [
                window.start_at,
                *[x.start_at for x in request.support_windows],
                *[x.at for x in anchors.values()],
            ]
        )
        snapshot_rows: list[sm.SourceSnapshotFields] = []
        prices = price_ids | {
            str(x.id)
            for x in series_rows
            if str(x.id) in benchmark_series and x.kind == "security_price"
        }
        providers = () if policy is None else policy.source_policy.provider_priority
        for model, condition in (
            (sm.PriceSnapshotModel, sm.PriceSnapshotModel.series_id.in_([UUID(x) for x in prices])),
            (sm.FxSnapshotModel, sm.FxSnapshotModel.provider_id.in_([UUID(x) for x in providers])),
            (
                sm.CorporateActionSnapshotModel,
                sm.CorporateActionSnapshotModel.series_id.in_([UUID(x) for x in action_ids]),
            ),
            (
                sm.BenchmarkSnapshotModel,
                sm.BenchmarkSnapshotModel.series_id.in_([UUID(x) for x in benchmark_series]),
            ),
        ):
            rows = session.scalars(
                select(model)
                .where(
                    model.owner_id == owner,
                    condition,
                    model.first_observed_at <= window.source_cutoff_at,
                    model.effective_at <= window.source_cutoff_at,
                    model.period_end >= start.date(),
                    model.period_start <= window.end_date,
                )
                .order_by(model.first_observed_at, model.id)
                .limit(257 - len(snapshot_rows))
            ).all()
            snapshot_rows.extend(rows)
            if len(snapshot_rows) > 256:
                raise error("RESULT_TOO_LARGE")
        observation_total = 0
        for observation_model, parent in (
            (sm.PriceObservationModel, sm.PriceSnapshotModel),
            (sm.FxObservationModel, sm.FxSnapshotModel),
            (sm.CorporateActionObservationModel, sm.CorporateActionSnapshotModel),
            (sm.BenchmarkObservationModel, sm.BenchmarkSnapshotModel),
        ):
            count = (
                session.scalar(
                    select(func.count())
                    .select_from(observation_model)
                    .where(
                        observation_model.snapshot_id.in_(
                            [x.id for x in snapshot_rows if isinstance(x, parent)]
                        )
                    )
                )
                or 0
            )
            observation_total += count
        if observation_total > 100000:
            raise error("RESULT_TOO_LARGE")
        calendars = {x.calendar_id for x in series_rows} | {
            x.calendar_id for x in snapshot_rows if isinstance(x, sm.FxSnapshotModel)
        }
        if policy_row is not None:
            calendars.add(policy_row.calendar_id)
        if benchmark_version is not None:
            version_row = self._sources._owned(
                session, owner, sm.BenchmarkVersionModel, benchmark_version.id
            )
            calendars.add(version_row.calendar_id)
        if (
            len(calendars) > 256
            or (
                session.scalar(
                    select(func.count())
                    .select_from(sm.SourceCalendarSessionModel)
                    .where(sm.SourceCalendarSessionModel.calendar_id.in_(calendars))
                )
                or 0
            )
            > 100000
        ):
            raise error("RESULT_TOO_LARGE")
        captured_calendars = tuple(
            self._sources._calendar(session, owner, x) for x in sorted(calendars, key=str)
        )
        for calendar_id in calendars:
            reference("calendar_version", calendar_id)
        reporting_calendar = next(
            (
                x
                for x in captured_calendars
                if request.reporting_calendar_ref is not None
                and (x.id, x.version)
                == (request.reporting_calendar_ref.id, request.reporting_calendar_ref.version)
            ),
            None,
        )
        cash_currencies = {x.currency for anchor in anchors.values() for x in anchor.cash}
        for event in events:
            money = getattr(event, "cash_impact", None) or getattr(event, "signed_amount", None)
            if money is not None:
                cash_currencies.add(money.currency)
        required_sessions = (
            0
            if reporting_calendar is None
            else sum(
                start.date() <= x.session_date <= window.end_date
                for x in reporting_calendar.sessions
            )
        )
        combined_cells = (required_sessions + len(anchors)) * (
            len(instruments) + len(cash_currencies)
        )
        combined_cells += required_sessions * len(benchmark_series)
        if combined_cells > 100000:
            raise error("RESULT_TOO_LARGE")
        snapshots = []
        for snapshot_row in snapshot_rows:
            self._sources._snapshot_permit(session, snapshot_row)
            kind = (
                "provider_benchmark_snapshot"
                if isinstance(snapshot_row, sm.BenchmarkSnapshotModel)
                else str(snapshot_row.__tablename__).removesuffix("s")
            )
            reference(kind, snapshot_row.id)
            reference("provider_license_version", snapshot_row.license_version_id)
            snapshots.append(self._sources._load_snapshot(session, snapshot_row))
        benchmark = (
            None
            if benchmark_version is None
            else d.CompositeBenchmarkInput(
                benchmark_version_id=benchmark_version.id,
                definition_id=benchmark_version.definition_id,
                content_digest=benchmark_version.content_digest,
                content=benchmark_version.content,
                published_at=benchmark_version.published_at,
                price_snapshots=tuple(
                    x
                    for x in snapshots
                    if isinstance(x, PriceSnapshot) and x.series.id in benchmark_series
                ),
                benchmark_snapshots=tuple(x for x in snapshots if isinstance(x, BenchmarkSnapshot)),
            )
        )
        target = self._target_grouping(
            session, principal, owner, account, request, tuple(instruments.values())
        )
        if target is not None:
            reference("target_version", target.version_id)
        coverage = (
            opening.bridge_coverage
            if isinstance(opening, (d.ObservedHistoricalOpening, d.InceptionHistoricalOpening))
            else d.HistoricalCoverage(
                measures=(
                    d.HistoricalCoverageMeasure(
                        key=d.HistoricalCoverageKey.OPENING,
                        expected_count=1,
                        available_count=0,
                        complete=False,
                        reasons=(d.HistoricalReason.OPENING_MISSING,),
                    ),
                )
            )
        )
        value = canonical_historical_input(
            d.HistoricalInput(
                owner_id=str(owner),
                account_id=str(account),
                selection=request,
                opening=opening,
                instruments=tuple(instruments.values()),
                event_candidates=tuple(events),
                activity_coverage=activity_coverage,
                valuation_anchors=tuple(anchors.values()),
                price_snapshots=tuple(
                    x
                    for x in snapshots
                    if isinstance(x, PriceSnapshot) and x.series.id in price_ids
                ),
                fx_snapshots=tuple(x for x in snapshots if isinstance(x, FxSnapshot)),
                action_snapshots=tuple(
                    x for x in snapshots if isinstance(x, CorporateActionSnapshot)
                ),
                calendars=captured_calendars,
                mapping_evidence=tuple(mappings),
                classification_evidence=classifications,
                sources=tuple(references.values()),
                coverage=coverage,
                benchmark_input=benchmark,
                target_grouping=target,
            )
        )
        while True:
            missing_parents = {
                parent for source in references.values() for parent in source.parent_ids
            } - {source.id for source in references.values()}
            if not missing_parents:
                break
            for parent_identifier in sorted(missing_parents):
                found = self._find_reference(session, owner, account, parent_identifier)
                references[(found.kind, found.id)] = found
            if len(references) > d.MAX_HISTORICAL_SOURCES:
                raise error("RESULT_TOO_LARGE")
        value = canonical_historical_input(replace(value, sources=tuple(references.values())))
        identity = historical_input_digest(value)
        old = session.scalar(
            select(hm.HistoricalInputModel).where(
                hm.HistoricalInputModel.owner_id == owner,
                hm.HistoricalInputModel.broker_account_id == account,
                hm.HistoricalInputModel.input_digest == identity,
            )
        )
        if old is not None:
            return self._capture_view(session, owner, old)
        row = hm.HistoricalInputModel(
            id=uuid4(),
            owner_id=owner,
            broker_account_id=account,
            policy_id=None if policy_row is None else policy_row.id,
            benchmark_version_id=None
            if request.benchmark_version_id is None
            else UUID(request.benchmark_version_id),
            target_version_id=None
            if request.target_version_id is None
            else UUID(request.target_version_id),
            period_start=window.start_date,
            period_end=window.end_date,
            source_cutoff_at=window.source_cutoff_at,
            reporting_currency=window.reporting_currency.value,
            knowledge_policy=window.knowledge_policy.value,
            input_digest=identity,
            request_digest=digest(request),
            canonical_input=encoded(value),
            sealed=False,
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        for instrument in value.instruments:
            session.add(
                hm.HistoricalInputInstrumentModel(
                    owner_id=owner,
                    input_id=row.id,
                    listing_id=UUID(instrument.listing_id),
                    instrument_id=UUID(instrument.instrument_id),
                    currency=instrument.native_currency.value,
                )
            )
        for source in value.sources:
            self._dependency(session, owner, source, input_id=row.id)
        for event in value.event_candidates:
            identity_value = event.identity
            kind = (
                "external_flow"
                if isinstance(event, d.HistoricalExternalFlow)
                else "unknown_activity"
                if isinstance(event, d.HistoricalUnknownActivity)
                else event.kind
            )
            money = (
                event.signed_amount
                if isinstance(event, (d.HistoricalCashEffect, d.HistoricalExternalFlow))
                else event.net
                if isinstance(event, d.HistoricalDividend)
                else event.cash_impact
                if isinstance(event, d.HistoricalExecution)
                else event.known_amount
                if isinstance(event, d.HistoricalUnknownActivity)
                else None
            )
            execution = event if isinstance(event, d.HistoricalExecution) else None
            session.add(
                hm.HistoricalEventModel(
                    owner_id=owner,
                    input_id=row.id,
                    revision_id=identity_value.revision_id,
                    economic_key=identity_value.economic_key,
                    kind=kind,
                    source_record_id=UUID(identity_value.source_record_id),
                    source_occurrence_id=None
                    if identity_value.source_occurrence_id is None
                    else UUID(identity_value.source_occurrence_id),
                    economic_at=identity_value.economic_at,
                    first_observed_at=identity_value.first_observed_at,
                    revision_sequence=identity_value.revision_sequence,
                    order_key=None if execution is None else execution.order_key,
                    fill_key=None if execution is None else execution.fill_key,
                    listing_id=None if execution is None else UUID(execution.listing_id),
                    instrument_id=None if execution is None else UUID(execution.instrument_id),
                    currency=None if money is None else money.currency.value,
                    amount=None if money is None else money.amount,
                    quantity=None if execution is None else execution.quantity,
                    price=None if execution is None else execution.native_price.amount,
                    canonical_event=encoded(event),
                )
            )
        session.flush()
        row.sealed = True
        session.flush()
        return self._capture_view(session, owner, row)

    def _target_grouping(
        self,
        session: Session,
        principal: Principal,
        owner: UUID,
        account: UUID,
        request: d.HistoricalSelectionRequest,
        instruments: tuple[d.HistoricalInstrument, ...],
    ) -> d.PinnedTargetGrouping | None:
        if request.target_version_id is None:
            return None
        self._authorizer.require_scope(principal, Scope.TARGETS_READ, now=self._now())
        row = session.scalar(
            select(TargetVersionModel).where(
                TargetVersionModel.owner_id == owner,
                TargetVersionModel.id == UUID(request.target_version_id),
            )
        )
        if row is None:
            raise error("NOT_FOUND")
        portfolio = session.get(VirtualPortfolioModel, row.virtual_portfolio_id)
        if (
            portfolio is None
            or portfolio.owner_id != owner
            or portfolio.broker_account_id not in (None, account)
        ):
            raise error("NOT_FOUND")
        if row.published_at is not None and row.published_at > request.window.source_cutoff_at:
            raise error("VALIDATION_FAILED")
        if (
            row.published_at is None
            or row.content_digest is None
            or portfolio.reporting_currency != request.window.reporting_currency.value
            or (
                portfolio.broker_account_id is None
                and request.grouping_policy != "explicit_comparison"
            )
        ):
            raise error("VALIDATION_FAILED")
        nodes = {
            x.id: x
            for x in session.scalars(
                select(TargetNodeModel)
                .where(TargetNodeModel.target_version_id == row.id)
                .limit(257)
            )
        }
        holdings = session.scalars(
            select(TargetHoldingModel)
            .where(TargetHoldingModel.target_version_id == row.id)
            .limit(257)
        ).all()
        if len(nodes) > 256 or len(holdings) > 256:
            raise error("RESULT_TOO_LARGE")
        assignments: list[d.PinnedTargetAssignment] = []
        for holding in holdings:
            node = nodes[holding.node_id]
            group = nodes.get(node.parent_id) if node.parent_id is not None else node
            assert group is not None
            assignments.extend(
                d.PinnedTargetAssignment(
                    listing_id=instrument.listing_id,
                    group_key=group.key,
                    group_name=group.name,
                )
                for instrument in instruments
                if str(holding.instrument_id) == instrument.instrument_id
                and (holding.listing_id is None or str(holding.listing_id) == instrument.listing_id)
            )
        return d.PinnedTargetGrouping(
            version_id=str(row.id),
            content_digest=row.content_digest,
            effective_at=row.effective_at,
            published_at=row.published_at,
            policy=cast(
                Literal["historical_assignment", "explicit_comparison"], request.grouping_policy
            ),
            assignments=tuple(assignments),
        )
