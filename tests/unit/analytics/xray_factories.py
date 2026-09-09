"""Explicitly sourced synthetic X-ray fixtures; independent tests may use integer/Fraction math."""

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from trading212_domain import xray as d
from trading212_domain.enums import QualityState, ValueOrigin
from trading212_domain.values import CurrencyCode, Instant, Money

EUR = CurrencyCode("EUR")
AT = Instant.parse("2025-12-31T00:00:00Z")
CUTOFF = Instant.parse("2026-09-07T12:00:00Z")


def uid(value: int) -> UUID:
    return UUID(int=value)


def metric(
    amount: str | Decimal | None, references: tuple[UUID, ...] = (), currency: CurrencyCode = EUR
) -> d.XrayMoneyMetric:
    return d.XrayMoneyMetric(
        None if amount is None else Money(Decimal(amount), currency),
        d.XrayReason.MISSING_FX if amount is None else None,
        QualityState.PARTIAL if amount is None else QualityState.FRESH,
        ValueOrigin.UNAVAILABLE if amount is None else ValueOrigin.OBSERVED_PROVIDER,
        d.XrayBound.EXACT,
        d.XrayAvailability.UNAVAILABLE if amount is None else d.XrayAvailability.AVAILABLE,
        Decimal("0.9"),
        references,
    )


class Builder:
    def __init__(self) -> None:
        self.sequence = 10_000
        self.dependencies: list[d.XraySourceDependency] = []
        self.positions: list[d.XrayPosition] = []
        self.broker_fx: list[d.XrayBrokerFx] = []
        self.licensed_fx: list[d.XrayLicensedFx] = []
        self.reporting_currency = EUR
        self.cash: list[d.XrayCash] = []
        self.definitions: list[d.XrayFundDefinition] = []
        self.mappings: list[d.XrayFundMapping] = []
        self.constituents: list[d.XrayConstituentCandidate] = []
        self.entities: list[d.XrayEntityEvidence] = []
        self.relationships: list[d.XrayRelationshipVersion] = []
        self.classifications: list[d.XrayClassificationBatch] = []
        self.policy = d.XrayPolicyVersion(
            uid(100),
            "1",
            d.XrayProviderSelectionPolicy(uid(101), "1", (str(uid(900)), str(uid(901)))),
            d.XrayIdentityPolicy(uid(102), "1"),
            d.XrayClassificationPolicy(uid(103), "1"),
            tuple(
                d.XrayTaxonomyVersion(
                    dimension, uid(200 + offset), "1", f"synthetic:{dimension.value}"
                )
                for offset, dimension in enumerate(
                    item for item in d.XrayDimension if item is not d.XrayDimension.COMPANY
                )
            ),
            d.XrayFreshnessPolicy(uid(104), "1", 31_536_000, "valuation_at"),
            d.XrayQualityPolicy(uid(105), "1"),
            d.XrayTraversalPolicy(uid(106), "1"),
            d.XrayUnconfiguredThresholds(),
            d.XrayLimits(),
        )

    def next_id(self) -> UUID:
        self.sequence += 1
        return uid(self.sequence)

    def reference(
        self,
        kind: d.XrayDependencyKind,
        subject_kind: d.XraySubjectKind,
        subject: UUID,
        *,
        internal: bool = False,
        record_id: UUID | None = None,
    ) -> UUID:
        reference = self.next_id()
        reference_kind = {
            d.XrayDependencyKind.VALUATION: d.XrayReferenceKind.SNAPSHOT_POSITION
            if subject_kind is d.XraySubjectKind.SNAPSHOT_POSITION
            else d.XrayReferenceKind.SNAPSHOT_CASH,
            d.XrayDependencyKind.FX: d.XrayReferenceKind.FX_SNAPSHOT,
            d.XrayDependencyKind.FUND_DEFINITION: d.XrayReferenceKind.FUND_DEFINITION,
            d.XrayDependencyKind.FUND_MAPPING: d.XrayReferenceKind.FUND_MAPPING,
            d.XrayDependencyKind.CONSTITUENTS: d.XrayReferenceKind.CONSTITUENT_SNAPSHOT,
            d.XrayDependencyKind.IDENTITY: d.XrayReferenceKind.ENTITY_EVIDENCE_REFERENCE,
            d.XrayDependencyKind.RELATIONSHIP: d.XrayReferenceKind.RELATIONSHIP,
            d.XrayDependencyKind.CLASSIFICATION: d.XrayReferenceKind.CLASSIFICATION_SNAPSHOT,
        }[kind]
        parent = (
            uid(3)
            if internal
            else subject
            if kind is d.XrayDependencyKind.CONSTITUENTS
            else uid(888)
            if kind in (d.XrayDependencyKind.IDENTITY, d.XrayDependencyKind.RELATIONSHIP)
            else next(
                item.evidence.id for item in self.definitions if item.instrument_id == subject
            )
            if kind is d.XrayDependencyKind.FUND_MAPPING
            else None
        )
        self.dependencies.append(
            d.XraySourceDependency(
                reference,
                uid(1),
                uid(2),
                uid(3),
                kind,
                subject_kind,
                subject,
                None if internal else str(uid(900)),
                None if internal else uid(999),
                sha256(str(reference).encode()).hexdigest(),
                d.XrayPhysicalReference(
                    reference_kind, subject if record_id is None else record_id, parent
                ),
            )
        )
        return reference

    def evidence(
        self, kind: d.XrayDependencyKind, subject_kind: d.XraySubjectKind, subject: UUID | None
    ) -> d.XrayEvidence:
        evidence_id = self.next_id()
        reference = self.reference(
            kind, subject_kind, evidence_id if subject is None else subject, record_id=evidence_id
        )
        return d.XrayEvidence(
            evidence_id,
            reference,
            AT,
            AT,
            None,
            1,
            d.XraySourceState.AVAILABLE,
            QualityState.FRESH,
            Decimal("0.9"),
        )

    def position(
        self,
        instrument: UUID,
        amount: str | None,
        *,
        position_id: UUID | None = None,
        listing: UUID | None = None,
    ) -> d.XrayPosition:
        position_id = self.next_id() if position_id is None else position_id
        reference = self.reference(
            d.XrayDependencyKind.VALUATION,
            d.XraySubjectKind.SNAPSHOT_POSITION,
            position_id,
            internal=True,
        )
        row = d.XrayPosition(
            d.PositionRoot(position_id, instrument, listing),
            metric(amount, (reference,)),
            metric(amount, (reference,)),
            (reference,),
            (),
        )
        self.positions.append(row)
        return row

    def broker_position(
        self, original: str = "62.50", reporting: str = "50", rate: str = "0.8"
    ) -> d.XrayBrokerFx:
        row = self.position(uid(10), reporting, listing=uid(501))
        source_record, calculation = self.next_id(), self.next_id()
        fx_reference, calculation_reference = self.next_id(), self.next_id()
        self.dependencies.extend(
            (
                d.XraySourceDependency(
                    fx_reference,
                    uid(1),
                    uid(2),
                    uid(3),
                    d.XrayDependencyKind.BROKER_FX,
                    d.XraySubjectKind.SOURCE_RECORD,
                    source_record,
                    None,
                    None,
                    "b" * 64,
                    d.XrayPhysicalReference(
                        d.XrayReferenceKind.BROKER_SOURCE_RECORD, source_record, uid(2)
                    ),
                ),
                d.XraySourceDependency(
                    calculation_reference,
                    uid(1),
                    uid(2),
                    uid(3),
                    d.XrayDependencyKind.VALUATION,
                    d.XraySubjectKind.SOURCE_RECORD,
                    calculation,
                    None,
                    None,
                    "c" * 64,
                    d.XrayPhysicalReference(d.XrayReferenceKind.CALCULATION_RUN, calculation, None),
                ),
            )
        )
        self.positions[-1] = replace(
            row,
            original_value=metric(original, row.valuation_refs, CurrencyCode("USD")),
            valuation_refs=(*row.valuation_refs, calculation_reference),
            fx_refs=(fx_reference,),
        )
        quote = d.XrayBrokerFx(
            row.root.key,
            fx_reference,
            calculation_reference,
            source_record,
            calculation,
            uid(501),
            CurrencyCode("USD"),
            EUR,
            Decimal(rate),
            AT,
            AT,
            "synthetic_wallet_quote",
            QualityState.FRESH,
            None,
        )
        self.broker_fx.append(quote)
        return quote

    def fx_leg(
        self,
        base: CurrencyCode,
        quote: CurrencyCode,
        rate: str,
        *,
        inverse: bool = False,
        snapshot_id: UUID | None = None,
    ) -> d.XrayFxLeg:
        reference = self.next_id()
        snapshot = self.next_id() if snapshot_id is None else snapshot_id
        observation = self.next_id()
        self.dependencies.append(
            d.XraySourceDependency(
                reference,
                uid(1),
                uid(2),
                uid(3),
                d.XrayDependencyKind.FX,
                d.XraySubjectKind.SOURCE_RECORD,
                observation,
                str(uid(900)),
                uid(999),
                "f" * 64,
                d.XrayPhysicalReference(d.XrayReferenceKind.FX_OBSERVATION, observation, snapshot),
            )
        )
        return d.XrayFxLeg(
            reference,
            snapshot,
            observation,
            base,
            quote,
            Decimal(rate),
            AT,
            AT,
            "divide" if inverse else "multiply",
            QualityState.FRESH,
            Decimal("0.8"),
        )

    def cash_row(self, amount: str, *, row_id: UUID | None = None) -> None:
        row_id = self.next_id() if row_id is None else row_id
        reference = self.reference(
            d.XrayDependencyKind.VALUATION, d.XraySubjectKind.SNAPSHOT_CASH, row_id, internal=True
        )
        self.cash.append(
            d.XrayCash(
                d.CashRoot(row_id, EUR),
                metric(amount, (reference,)),
                metric(amount, (reference,)),
                (reference,),
                (),
            )
        )

    def identity(self, instrument: UUID, entity: UUID, *, listing: UUID | None = None) -> None:
        evidence = self.evidence(
            d.XrayDependencyKind.IDENTITY, d.XraySubjectKind.INSTRUMENT, instrument
        )
        self.entities.append(d.XrayEntityEvidence(instrument, listing, entity, evidence))

    def classifications_for(self, entity: UUID, *, key: str = "known") -> None:
        evidence = self.evidence(
            d.XrayDependencyKind.CLASSIFICATION, d.XraySubjectKind.SOURCE_RECORD, None
        )
        rows = tuple(
            d.XrayClassificationAssignment(
                self.next_id(),
                d.XraySubjectKind.ENTITY,
                entity,
                taxonomy.dimension,
                taxonomy.taxonomy_id,
                taxonomy.version,
                "EUR" if taxonomy.dimension is d.XrayDimension.CURRENCY else key,
                Decimal("0.8"),
            )
            for taxonomy in self.policy.taxonomy_versions
        )
        self.classifications.append(d.XrayClassificationBatch(evidence, rows))

    def fund(
        self, instrument: UUID, holdings: tuple[tuple[UUID | None, str], ...]
    ) -> d.XrayConstituentCandidate:
        definition = self.evidence(
            d.XrayDependencyKind.FUND_DEFINITION, d.XraySubjectKind.INSTRUMENT, instrument
        )
        self.definitions.append(d.XrayFundDefinition(instrument, definition))
        mapping = d.XrayFundMapping(
            self.next_id(),
            instrument,
            self.evidence(
                d.XrayDependencyKind.FUND_MAPPING, d.XraySubjectKind.INSTRUMENT, instrument
            ),
        )
        self.mappings.append(mapping)
        candidate = d.XrayConstituentCandidate(
            self.next_id(),
            mapping.id,
            self.evidence(
                d.XrayDependencyKind.CONSTITUENTS, d.XraySubjectKind.FUND_MAPPING, mapping.id
            ),
            tuple(
                d.XrayConstituentHolding(
                    self.next_id(),
                    d.XrayHoldingKind.CASH if subject is None else d.XrayHoldingKind.INSTRUMENT,
                    subject,
                    None,
                    Decimal(weight),
                    None,
                    f"source:{index}",
                    EUR,
                    None if subject is None else f"evidence:{subject}",
                    Decimal("0.9"),
                )
                for index, (subject, weight) in enumerate(holdings)
            ),
            sum(
                (Decimal(weight) for subject, weight in holdings if subject is not None),
                Decimal("0"),
            ),
            Decimal("0"),
            sum((Decimal(weight) for subject, weight in holdings if subject is None), Decimal("0")),
        )
        self.constituents.append(candidate)
        return candidate

    def finish(self) -> d.XrayInput:
        roots: tuple[d.XrayPosition | d.XrayCash, ...] = (*self.positions, *self.cash)
        complete = all(item.reporting_value.value is not None for item in roots)
        amount = (
            sum(
                (
                    item.reporting_value.value.amount
                    for item in roots
                    if item.reporting_value.value is not None
                ),
                Decimal("0"),
            )
            if complete
            else None
        )
        total = metric(amount, currency=self.reporting_currency)
        return d.XrayInput(
            uid(1),
            uid(2),
            uid(3),
            "a" * 64,
            AT,
            CUTOFF,
            self.reporting_currency,
            self.policy,
            tuple(self.positions),
            tuple(self.cash),
            total,
            d.XrayValuationCoverage(
                complete,
                tuple(item.root.key for item in roots if item.reporting_value.value is not None),
                tuple(item.root.key for item in roots if item.reporting_value.value is None),
            ),
            d.XrayReconciliation(
                total,
                total,
                metric("0" if complete else None, currency=self.reporting_currency),
                (),
            ),
            tuple(self.definitions),
            tuple(self.mappings),
            tuple(self.constituents),
            tuple(self.entities),
            tuple(self.relationships),
            tuple(self.classifications),
            tuple(self.dependencies),
            tuple(self.broker_fx),
            tuple(self.licensed_fx),
        )


def fixture() -> d.XrayInput:
    builder = Builder()
    builder.position(uid(10), "200", position_id=uid(1000))
    builder.position(uid(20), "500", position_id=uid(1001))
    builder.position(uid(30), "300", position_id=uid(1002))
    builder.identity(uid(10), uid(110))
    builder.identity(uid(11), uid(111))
    builder.classifications_for(uid(110), key="alpha")
    builder.classifications_for(uid(111), key="beta")
    builder.fund(uid(20), ((uid(10), "0.6"), (uid(11), "0.3")))
    builder.fund(uid(30), ((uid(10), "0.2"), (uid(11), "0.8")))
    return builder.finish()


def reversed_input(value: d.XrayInput) -> d.XrayInput:
    return replace(
        value,
        policy=replace(
            value.policy, taxonomy_versions=tuple(reversed(value.policy.taxonomy_versions))
        ),
        positions=tuple(reversed(value.positions)),
        cash=tuple(reversed(value.cash)),
        fund_definitions=tuple(reversed(value.fund_definitions)),
        fund_mappings=tuple(reversed(value.fund_mappings)),
        constituent_candidates=tuple(
            replace(item, holdings=tuple(reversed(item.holdings)))
            for item in reversed(value.constituent_candidates)
        ),
        entity_evidence=tuple(reversed(value.entity_evidence)),
        relationship_versions=tuple(reversed(value.relationship_versions)),
        classification_batches=tuple(
            replace(item, assignments=tuple(reversed(item.assignments)))
            for item in reversed(value.classification_batches)
        ),
        source_dependencies=tuple(reversed(value.source_dependencies)),
    )
