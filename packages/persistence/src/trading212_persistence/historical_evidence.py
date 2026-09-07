"""Atomic fixed-purpose historical evidence registration and independent proof checks."""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from trading212_application.historical_evidence import (
    HistoricalEvidenceRegistration,
    HistoricalEvidenceView,
    HistoricalPolicyRegistration,
    HistoricalPolicyView,
)
from trading212_domain import historical as d
from trading212_domain.historical_serialization import historical_value_from_json
from trading212_domain.sources import SourceSeriesKind, SourceUse
from trading212_domain.values import require_bounded_text
from trading212_security.principals import Principal

from . import historical_models as hm
from . import models as lm
from . import source_models as sm
from .historical_base import HistoricalStoreBase, digest, encoded, error


class HistoricalEvidenceRegistrationStore(HistoricalStoreBase):
    def _policy_view(self, row: hm.HistoricalPolicyModel) -> HistoricalPolicyView:
        return HistoricalPolicyView(
            registration=historical_value_from_json(
                row.canonical_policy, HistoricalPolicyRegistration
            ),
            first_observed_at=row.first_observed_at,
            content_digest=row.content_digest,
        )

    def _evidence_view(self, row: hm.HistoricalEvidenceModel) -> HistoricalEvidenceView:
        return HistoricalEvidenceView(
            registration=historical_value_from_json(
                row.canonical_evidence, HistoricalEvidenceRegistration
            ),
            first_observed_at=row.first_observed_at,
            content_digest=row.content_digest,
        )

    async def register_historical_policy(
        self,
        principal: Principal,
        account_id: str,
        registration: HistoricalPolicyRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HistoricalPolicyView:
        require_bounded_text(correlation_id, field="correlation_id", maximum=100)

        def register(session: Session, owner: UUID, account: UUID | None) -> HistoricalPolicyView:
            assert account is not None
            calendar = session.scalar(
                select(sm.SourceCalendarModel).where(
                    sm.SourceCalendarModel.owner_id == owner,
                    sm.SourceCalendarModel.key == registration.reporting_calendar_ref.id,
                    sm.SourceCalendarModel.version == registration.reporting_calendar_ref.version,
                )
            )
            if calendar is None:
                raise error("NOT_FOUND")
            for identifier in registration.source_policy.provider_priority:
                self._sources._owned(session, owner, sm.MarketDataProviderModel, identifier)
            for identifier in (*registration.price_series_ids, *registration.action_series_ids):
                series = self._sources._owned(
                    session, owner, sm.MarketSourceSeriesModel, identifier
                )
                if (
                    series.kind != SourceSeriesKind.SECURITY_PRICE.value
                    or str(series.provider_id) not in registration.source_policy.provider_priority
                ):
                    raise error("VALIDATION_FAILED")
                self._sources._permit(session, owner, series.license_version_id, SourceUse.DISPLAY)
            previous, signature = self._command(
                session, owner, account, "historical.policy.register", idempotency_key, registration
            )
            if previous is not None:
                assert previous.policy_id is not None
                return self._policy_view(
                    self._owned(session, owner, hm.HistoricalPolicyModel, previous.policy_id)
                )
            existing = session.scalar(
                select(hm.HistoricalPolicyModel).where(
                    hm.HistoricalPolicyModel.owner_id == owner,
                    hm.HistoricalPolicyModel.broker_account_id == account,
                    hm.HistoricalPolicyModel.key == registration.key,
                )
            )
            if existing is not None:
                if self._policy_view(existing).registration != registration:
                    raise error("VALIDATION_FAILED")
                row = existing
            else:
                if registration.effective_at > self._now():
                    raise error("VALIDATION_FAILED")
                row = hm.HistoricalPolicyModel(
                    id=UUID(registration.id),
                    owner_id=owner,
                    broker_account_id=account,
                    key=registration.key,
                    effective_at=registration.effective_at,
                    first_observed_at=self._now(),
                    created_at=self._now(),
                    calendar_id=calendar.id,
                    content_digest=digest(registration),
                    canonical_policy=encoded(registration),
                    sealed=False,
                )
                session.add(row)
                session.flush()
                for kind, identifiers in (
                    ("price", registration.price_series_ids),
                    ("action", registration.action_series_ids),
                    ("fx_provider", registration.source_policy.provider_priority),
                ):
                    for ordinal, identifier in enumerate(identifiers):
                        session.add(
                            hm.HistoricalPolicySourceModel(
                                owner_id=owner,
                                policy_id=row.id,
                                kind=kind,
                                ordinal=ordinal,
                                series_id=UUID(identifier) if kind != "fx_provider" else None,
                                provider_id=UUID(identifier) if kind == "fx_provider" else None,
                            )
                        )
                session.flush()
                row.sealed = True
            self._record_command(
                session,
                principal,
                account,
                "historical.policy.register",
                idempotency_key,
                signature,
                correlation_id,
                policy_id=row.id,
            )
            return self._policy_view(row)

        return await self._run(principal, account_id, register, write=True)

    def _check_anchor(
        self, session: Session, owner: UUID, account: UUID, anchor: d.HistoricalValuationAnchor
    ) -> tuple[d.HistoricalSourceReference, ...]:
        if not anchor.source_refs or not anchor.reconciliation.anchor_refs:
            raise error("VALIDATION_FAILED")
        references = tuple(
            self._find_reference(session, owner, account, x)
            for x in set((*anchor.source_refs, *anchor.reconciliation.anchor_refs))
        )
        positions = {x.listing_id: x for x in anchor.positions}
        cash = {x.currency: x.amount for x in anchor.cash}
        for position in anchor.positions:
            listing = session.get(lm.ListingModel, UUID(position.listing_id))
            if listing is None or listing.instrument_id != UUID(position.instrument_id):
                raise error("NOT_FOUND")
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_EVEN
            for line in anchor.reconciliation.lines:
                if line.state == "unavailable":
                    continue
                if (
                    line.expected is None
                    or line.observed is None
                    or line.residual is None
                    or line.observed - line.expected != line.residual
                ):
                    raise error("VALIDATION_FAILED")
                if (abs(line.residual) <= line.tolerance) != (line.state == "reconciled"):
                    raise error("VALIDATION_FAILED")
                if line.kind == "cash":
                    actual = None if line.currency is None else cash.get(line.currency)
                else:
                    holding = positions.get(line.identity)
                    actual = (
                        None
                        if holding is None
                        else holding.quantity
                        if line.kind == "quantity"
                        else None
                        if holding.acquisition_cost.value is None
                        else holding.acquisition_cost.value.amount
                    )
                if actual is None or actual != line.observed:
                    raise error("VALIDATION_FAILED")
            if anchor.reconciliation.outcome == "reconciled":
                expected_keys = {("quantity", x.listing_id) for x in anchor.positions} | {
                    ("cash", x.currency.value) for x in anchor.cash
                }
                actual_keys = {
                    (x.kind, x.identity)
                    for x in anchor.reconciliation.lines
                    if x.state == "reconciled"
                }
                if not expected_keys <= actual_keys or any(
                    x.state != "reconciled" for x in anchor.reconciliation.lines
                ):
                    raise error("VALIDATION_FAILED")
        # A canonical snapshot reference is an independently retained observation, not a label.
        for reference in references:
            if reference.kind != "portfolio_snapshot":
                continue
            rows = session.scalars(
                select(lm.SnapshotPositionModel)
                .where(lm.SnapshotPositionModel.snapshot_id == UUID(reference.id))
                .limit(257)
            ).all()
            balances = session.scalars(
                select(lm.SnapshotCashModel)
                .where(lm.SnapshotCashModel.snapshot_id == UUID(reference.id))
                .limit(33)
            ).all()
            snapshot = session.get(lm.PortfolioSnapshotModel, UUID(reference.id))
            assert snapshot is not None
            if (
                snapshot.valuation_at != anchor.at
                or len(rows) != len(positions)
                or len(balances) != len(cash)
            ):
                raise error("VALIDATION_FAILED")
            for row in rows:
                value = positions.get(str(row.listing_id))
                if (
                    value is None
                    or value.quantity != row.quantity
                    or (
                        value.market_value.value is not None
                        and (
                            value.market_value.value.amount != row.market_value
                            or value.market_value.value.currency.value != row.currency
                        )
                    )
                ):
                    raise error("VALIDATION_FAILED")
            actual_cash = {x.currency.value: x.amount for x in anchor.cash}
            if any(actual_cash.get(row.currency) != row.amount for row in balances):
                raise error("VALIDATION_FAILED")
        with localcontext() as context:
            context.prec = 80
            context.rounding = ROUND_HALF_EVEN
            self._check_record_anchor(session, account, anchor, references)
        return references

    def _check_record_anchor(
        self,
        session: Session,
        account: UUID,
        anchor: d.HistoricalValuationAnchor,
        references: tuple[d.HistoricalSourceReference, ...],
    ) -> None:
        from .historical_normalization import number, obj

        records = tuple(
            session.get(lm.SourceRecordModel, UUID(reference.id))
            for reference in references
            if reference.kind == "broker_source_record"
        )
        if not records:
            return
        positions = {x.listing_id: x for x in anchor.positions}
        observed_positions: set[str] = set()
        observed_cash: dict[str, Decimal] = {}
        account_observed = False
        for record in records:
            assert record is not None
            if record.broker_account_id != account:
                raise error("NOT_FOUND")
            if record.capability not in {"account_summary", "portfolio_positions"}:
                continue
            if record.source_updated_at != anchor.at:
                dated = session.scalar(
                    select(lm.SourceRecordOccurrenceModel.id)
                    .where(
                        lm.SourceRecordOccurrenceModel.source_record_id == record.id,
                        lm.SourceRecordOccurrenceModel.source_updated_at == anchor.at,
                        lm.SourceRecordOccurrenceModel.observed_at <= self._now(),
                    )
                    .limit(1)
                )
                if dated is None:
                    raise error("VALIDATION_FAILED")
            body = obj(record.sanitized_payload)
            if record.capability == "portfolio_positions":
                instrument = obj(body.get("instrument"))
                ticker = instrument.get("ticker")
                listing = session.scalar(
                    select(lm.ListingModel).where(
                        lm.ListingModel.provider == record.provider,
                        lm.ListingModel.provider_instrument_id == ticker,
                        lm.ListingModel.id.in_([UUID(x) for x in positions]),
                    )
                )
                if listing is None or str(listing.id) in observed_positions:
                    raise error("VALIDATION_FAILED")
                holding = positions[str(listing.id)]
                wallet = obj(body.get("walletImpact"))
                if number(body.get("quantity")) != holding.quantity:
                    raise error("VALIDATION_FAILED")
                for expected, field in (
                    (holding.market_value, "currentValue"),
                    (holding.acquisition_cost, "totalCost"),
                ):
                    if expected.value is not None and (
                        wallet.get("currency") != expected.value.currency.value
                        or number(wallet.get(field)) != expected.value.amount
                    ):
                        raise error("VALIDATION_FAILED")
                price = number(body.get("currentPrice"))
                if holding.market_value.value is not None and (
                    price is None
                    or instrument.get("currency") != holding.market_value.value.currency.value
                    or price * holding.quantity != holding.market_value.value.amount
                ):
                    raise error("VALIDATION_FAILED")
                observed_positions.add(str(listing.id))
            else:
                if account_observed:
                    raise error("VALIDATION_FAILED")
                account_observed = True
                cash = obj(body.get("cash"))
                currency = body.get("currency")
                amounts = tuple(
                    number(cash.get(field))
                    for field in ("availableToTrade", "inPies", "reservedForOrders")
                )
                if not isinstance(currency, str) or any(x is None for x in amounts):
                    raise error("VALIDATION_FAILED")
                observed_cash[currency] = sum((x for x in amounts if x is not None), Decimal(0))
        if observed_positions != set(positions) or not account_observed:
            raise error("VALIDATION_FAILED")
        if {x.currency.value: x.amount for x in anchor.cash if x.amount != 0} != {
            currency: value for currency, value in observed_cash.items() if value != 0
        }:
            raise error("VALIDATION_FAILED")

    def _persist_anchor(
        self, session: Session, owner: UUID, evidence_id: UUID, anchor: d.HistoricalValuationAnchor
    ) -> None:
        row = hm.HistoricalAnchorModel(
            id=UUID(anchor.id),
            owner_id=owner,
            evidence_id=evidence_id,
            anchor_key=anchor.id,
            at=anchor.at,
            timing=anchor.timing,
            origin=anchor.origin.value,
            canonical_anchor=encoded(anchor),
        )
        session.add(row)
        session.flush()
        for value in anchor.positions:
            listing = session.get(lm.ListingModel, UUID(value.listing_id))
            assert listing is not None
            money = value.market_value.value or value.acquisition_cost.value
            session.add(
                hm.HistoricalAnchorPositionModel(
                    owner_id=owner,
                    anchor_id=row.id,
                    listing_id=UUID(value.listing_id),
                    instrument_id=UUID(value.instrument_id),
                    quantity=value.quantity,
                    currency=listing.trading_currency if money is None else money.currency.value,
                    value=None
                    if value.market_value.value is None
                    else value.market_value.value.amount,
                    acquisition_cost=None
                    if value.acquisition_cost.value is None
                    else value.acquisition_cost.value.amount,
                )
            )
        for cash_value in anchor.cash:
            session.add(
                hm.HistoricalAnchorCashModel(
                    owner_id=owner,
                    anchor_id=row.id,
                    currency=cash_value.currency.value,
                    amount=cash_value.amount,
                )
            )
        for ordinal, proof_line in enumerate(anchor.reconciliation.lines):
            session.add(
                hm.HistoricalReconciliationLineModel(
                    owner_id=owner,
                    anchor_id=row.id,
                    ordinal=ordinal,
                    kind=proof_line.kind,
                    identity=proof_line.identity,
                    currency=None if proof_line.currency is None else proof_line.currency.value,
                    expected=proof_line.expected,
                    observed=proof_line.observed,
                    residual=proof_line.residual,
                    tolerance=proof_line.tolerance,
                    state=proof_line.state,
                )
            )

    async def register_historical_evidence(
        self,
        principal: Principal,
        account_id: str,
        evidence: HistoricalEvidenceRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> HistoricalEvidenceView:
        require_bounded_text(correlation_id, field="correlation_id", maximum=100)

        def register(session: Session, owner: UUID, account: UUID | None) -> HistoricalEvidenceView:
            assert account is not None
            references: dict[str, d.HistoricalSourceReference] = {}
            anchors = list(evidence.valuation_anchors)
            if isinstance(evidence.opening, d.ObservedHistoricalOpening):
                anchors.append(evidence.opening.anchor)
            for anchor in {x.id: x for x in anchors}.values():
                for reference in self._check_anchor(session, owner, account, anchor):
                    references[reference.id] = reference
            if isinstance(evidence.opening, d.InceptionHistoricalOpening):
                for identifier in evidence.opening.source_refs:
                    references[identifier] = self._find_reference(
                        session, owner, account, identifier
                    )
            for classification in evidence.classifications:
                self._sources._permit(
                    session, owner, UUID(classification.license_version_id), SourceUse.DISPLAY
                )
                if session.get(lm.InstrumentModel, UUID(classification.instrument_id)) is None:
                    raise error("NOT_FOUND")
                for identifier in (*classification.source_refs, classification.license_version_id):
                    references[identifier] = self._find_reference(
                        session, owner, account, identifier
                    )
            for chunk in evidence.activity_coverage:
                run = session.get(lm.IngestionRunModel, UUID(chunk.ingestion_run_id))
                if run is None or run.broker_account_id != account:
                    raise error("NOT_FOUND")
                if (
                    run.status != "succeeded"
                    or run.mode != "full"
                    or run.completed_at is None
                    or run.completed_at > self._now()
                    or chunk.capability not in run.effective_capabilities
                    or chunk.end_at > self._now()
                ):
                    raise error("VALIDATION_FAILED")
                observed_end = session.scalar(
                    select(func.max(lm.SourceRecordOccurrenceModel.source_updated_at))
                    .join(
                        lm.SourceRecordModel,
                        lm.SourceRecordModel.id == lm.SourceRecordOccurrenceModel.source_record_id,
                    )
                    .where(
                        lm.SourceRecordOccurrenceModel.ingestion_run_id == run.id,
                        lm.SourceRecordModel.broker_account_id == account,
                        lm.SourceRecordModel.capability.in_(
                            ("account_summary", "portfolio_positions")
                        ),
                        lm.SourceRecordOccurrenceModel.observed_at <= self._now(),
                    )
                )
                if observed_end is None or observed_end < chunk.end_at:
                    raise error("VALIDATION_FAILED")
                references[str(run.id)] = self._reference(
                    session, owner, account, "ingestion_run", run.id
                )
            if len(references) > d.MAX_HISTORICAL_SOURCES:
                raise error("RESULT_TOO_LARGE")
            previous, signature = self._command(
                session, owner, account, "historical.evidence.register", idempotency_key, evidence
            )
            if previous is not None:
                assert previous.evidence_id is not None
                self._reauthorize(session, owner, account, evidence_id=previous.evidence_id)
                return self._evidence_view(
                    self._owned(session, owner, hm.HistoricalEvidenceModel, previous.evidence_id)
                )
            # The trusted receipt time is never supplied by the registration caller.
            observed = replace(
                evidence,
                classifications=tuple(
                    replace(x, first_observed_at=self._now()) for x in evidence.classifications
                ),
            )
            row = hm.HistoricalEvidenceModel(
                id=UUID(evidence.id),
                owner_id=owner,
                broker_account_id=account,
                key=evidence.key,
                first_observed_at=self._now(),
                created_at=self._now(),
                content_digest=digest(observed),
                canonical_evidence=encoded(observed),
                sealed=False,
            )
            session.add(row)
            session.flush()
            for anchor in {x.id: x for x in anchors}.values():
                self._persist_anchor(session, owner, row.id, anchor)
            for chunk in observed.activity_coverage:
                session.add(
                    hm.HistoricalActivityCoverageModel(
                        id=UUID(chunk.id),
                        owner_id=owner,
                        evidence_id=row.id,
                        ingestion_run_id=UUID(chunk.ingestion_run_id),
                        capability=chunk.capability,
                        start_at=chunk.start_at,
                        end_at=chunk.end_at,
                        first_observed_at=self._now(),
                        coverage_complete=chunk.coverage_complete,
                    )
                )
            for value in observed.classifications:
                session.add(
                    hm.HistoricalClassificationModel(
                        id=UUID(value.id),
                        owner_id=owner,
                        evidence_id=row.id,
                        instrument_id=UUID(value.instrument_id),
                        dimension=value.dimension,
                        taxonomy=value.taxonomy,
                        taxonomy_version=value.taxonomy_version,
                        category=value.category,
                        valid_from=value.valid_from,
                        valid_to=value.valid_to,
                        first_observed_at=value.first_observed_at,
                        license_version_id=UUID(value.license_version_id),
                        canonical_classification=encoded(value),
                    )
                )
            session.flush()
            for reference in references.values():
                self._dependency(session, owner, reference, evidence_id=row.id)
            session.flush()
            row.sealed = True
            self._record_command(
                session,
                principal,
                account,
                "historical.evidence.register",
                idempotency_key,
                signature,
                correlation_id,
                evidence_id=row.id,
            )
            return self._evidence_view(row)

        return await self._run(principal, account_id, register, write=True)
