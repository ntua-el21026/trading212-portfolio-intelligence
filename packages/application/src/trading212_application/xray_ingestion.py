"""Typed internal X-ray policy/catalog/evidence commands; no public write surface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from trading212_domain.errors import fail_validation
from trading212_domain.sources import source_id, source_integer, source_key, source_tuple
from trading212_domain.values import exact_decimal, require_utc
from trading212_domain.xray import XrayDimension, XrayPolicyVersion
from trading212_security.principals import Principal

from .source_providers import (
    ClassificationPage,
    ClassificationRequest,
    ConstituentPage,
    ConstituentRequest,
)


def _confidence(value: Decimal | None) -> None:
    if value is not None and (
        not isinstance(value, Decimal)
        or not Decimal("0") <= exact_decimal(value, field="confidence") <= Decimal("1")
    ):
        fail_validation(
            "Confidence must be a sourced Decimal fraction or null.", field="confidence"
        )


class _EvidenceInterval(Protocol):
    @property
    def effective_at(self) -> datetime: ...

    @property
    def valid_until(self) -> datetime | None: ...


class _Identified(Protocol):
    @property
    def id(self) -> str: ...


def _interval(value: _EvidenceInterval) -> None:
    start = value.effective_at
    end = value.valid_until
    object.__setattr__(value, "effective_at", require_utc(start, field="effective_at"))
    if end is not None:
        object.__setattr__(value, "valid_until", require_utc(end, field="valid_until"))
        if end <= start:
            fail_validation("Evidence validity must be nonempty.", field="valid_until")


def _unique(values: tuple[_Identified, ...], field_name: str) -> None:
    identifiers = tuple(value.id for value in values)
    if len(set(identifiers)) != len(identifiers):
        fail_validation("Registration row identities must be unique.", field=field_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayTaxonomyRegistration:
    id: str
    dimension: XrayDimension
    key: str
    version: str

    def __post_init__(self) -> None:
        source_id(self.id)
        if not isinstance(self.dimension, XrayDimension) or self.dimension is XrayDimension.COMPANY:
            fail_validation("A classification taxonomy dimension is required.", field="dimension")
        source_key(self.key, "taxonomy_key")
        source_key(self.version, "taxonomy_version")


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayPolicyRegistration:
    key: str
    effective_at: datetime
    policy: XrayPolicyVersion
    taxonomies: tuple[XrayTaxonomyRegistration, ...]

    def __post_init__(self) -> None:
        source_key(self.key)
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        if not isinstance(self.policy, XrayPolicyVersion):
            fail_validation("A typed X-ray policy is required.", field="policy")
        source_tuple(self.taxonomies, XrayTaxonomyRegistration, "taxonomies", 5)
        _unique(self.taxonomies, "taxonomies")
        declared = {
            (str(row.taxonomy_id), row.dimension, row.version)
            for row in self.policy.taxonomy_versions
        }
        registered = {(row.id, row.dimension, row.version) for row in self.taxonomies}
        if declared != registered:
            fail_validation(
                "Policy taxonomy identities must match their registration.", field="taxonomies"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class EconomicEntityRegistration:
    id: str
    key: str
    display_name: str
    lei: str | None = None

    def __post_init__(self) -> None:
        source_id(self.id)
        source_key(self.key)
        if not isinstance(self.display_name, str) or not 1 <= len(self.display_name) <= 300:
            fail_validation("A bounded entity name is required.", field="display_name")
        if self.lei is not None:
            import re

            if not isinstance(self.lei, str) or re.fullmatch(r"[A-Z0-9]{20}", self.lei) is None:
                fail_validation("A canonical LEI is required.", field="lei")


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityMappingRegistration:
    id: str
    instrument_id: str
    entity_id: str
    listing_id: str | None
    effective_at: datetime
    valid_until: datetime | None
    confidence: Decimal | None

    def __post_init__(self) -> None:
        for name in ("id", "instrument_id", "entity_id"):
            source_id(getattr(self, name), name)
        if self.listing_id is not None:
            source_id(self.listing_id, "listing_id")
        _interval(self)
        _confidence(self.confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class ShareClassRegistration:
    id: str
    instrument_id: str
    entity_id: str
    class_key: str
    effective_at: datetime
    valid_until: datetime | None
    confidence: Decimal | None

    def __post_init__(self) -> None:
        for name in ("id", "instrument_id", "entity_id"):
            source_id(getattr(self, name), name)
        source_key(self.class_key, "class_key")
        _interval(self)
        _confidence(self.confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityRelationshipRegistration:
    id: str
    kind: Literal["listing_of", "share_class_of", "depositary_receipt_of", "issuer_parent"]
    effective_at: datetime
    valid_until: datetime | None
    confidence: Decimal | None
    instrument_id: str | None = None
    listing_id: str | None = None
    share_class_id: str | None = None
    entity_id: str | None = None
    underlying_instrument_id: str | None = None
    parent_entity_id: str | None = None
    units_per_receipt: Decimal | None = None

    def __post_init__(self) -> None:
        source_id(self.id)
        for name in (
            "instrument_id",
            "listing_id",
            "share_class_id",
            "entity_id",
            "underlying_instrument_id",
            "parent_entity_id",
        ):
            value = getattr(self, name)
            if value is not None:
                source_id(value, name)
        _interval(self)
        _confidence(self.confidence)
        present = frozenset(
            name
            for name in (
                "instrument_id",
                "listing_id",
                "share_class_id",
                "entity_id",
                "underlying_instrument_id",
                "parent_entity_id",
                "units_per_receipt",
            )
            if getattr(self, name) is not None
        )
        expected = {
            "listing_of": frozenset(("listing_id", "instrument_id")),
            "share_class_of": frozenset(("instrument_id", "share_class_id", "entity_id")),
            "depositary_receipt_of": frozenset(
                ("instrument_id", "underlying_instrument_id", "entity_id", "units_per_receipt")
            ),
            "issuer_parent": frozenset(("entity_id", "parent_entity_id")),
        }
        if self.kind not in expected or present != expected[self.kind]:
            fail_validation("Relationship endpoints must match their closed kind.", field="kind")
        if self.units_per_receipt is not None and (
            not isinstance(self.units_per_receipt, Decimal)
            or exact_decimal(self.units_per_receipt, field="units_per_receipt") <= Decimal("0")
        ):
            fail_validation(
                "A positive Decimal receipt ratio is required.", field="units_per_receipt"
            )
        if (
            self.kind == "depositary_receipt_of"
            and self.instrument_id == self.underlying_instrument_id
        ):
            fail_validation("A receipt cannot refer to itself.", field="underlying_instrument_id")
        if self.kind == "issuer_parent" and self.entity_id == self.parent_entity_id:
            fail_validation("An issuer cannot be its own parent.", field="parent_entity_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityEvidenceRegistration:
    id: str
    key: str
    provider_id: str
    license_version_id: str
    revision: int
    effective_at: datetime
    valid_until: datetime | None
    entities: tuple[EconomicEntityRegistration, ...] = ()
    mappings: tuple[EntityMappingRegistration, ...] = ()
    share_classes: tuple[ShareClassRegistration, ...] = ()
    relationships: tuple[EntityRelationshipRegistration, ...] = ()

    def __post_init__(self) -> None:
        for name in ("id", "provider_id", "license_version_id"):
            source_id(getattr(self, name), name)
        source_key(self.key)
        source_integer(self.revision, "revision", 1, 2147483647)
        _interval(self)
        for name, kind in (
            ("entities", EconomicEntityRegistration),
            ("mappings", EntityMappingRegistration),
            ("share_classes", ShareClassRegistration),
            ("relationships", EntityRelationshipRegistration),
        ):
            values = getattr(self, name)
            source_tuple(values, kind, name, 100000)
            _unique(values, name)
        total = sum(
            len(values)
            for values in (self.entities, self.mappings, self.share_classes, self.relationships)
        )
        if not 1 <= total <= 100000:
            fail_validation(
                "A bounded nonempty evidence registration is required.", field="evidence"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class FundDefinitionRegistration:
    id: str
    key: str
    instrument_id: str
    fund_type: str
    provider_id: str
    license_version_id: str
    revision: int
    effective_at: datetime
    valid_until: datetime | None
    evidence_key: str
    confidence: Decimal | None
    share_class_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("id", "instrument_id", "provider_id", "license_version_id"):
            source_id(getattr(self, name), name)
        for name in ("key", "fund_type", "evidence_key"):
            source_key(getattr(self, name), name)
        if self.share_class_id is not None:
            source_id(self.share_class_id, "share_class_id")
        source_integer(self.revision, "revision", 1, 2147483647)
        _interval(self)
        _confidence(self.confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class FundSourceMappingRegistration:
    id: str
    fund_definition_id: str
    provider_id: str
    license_version_id: str
    provider_fund_key: str
    revision: int
    effective_at: datetime
    valid_until: datetime | None
    evidence_key: str
    confidence: Decimal | None

    def __post_init__(self) -> None:
        for name in ("id", "fund_definition_id", "provider_id", "license_version_id"):
            source_id(getattr(self, name), name)
        source_key(self.provider_fund_key, "provider_fund_key")
        source_key(self.evidence_key, "evidence_key")
        source_integer(self.revision, "revision", 1, 2147483647)
        _interval(self)
        _confidence(self.confidence)


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayRegistrationReceipt:
    id: str
    content_digest: str
    first_observed_at: datetime


class XrayIngestionService(Protocol):
    """Internal writes use actual licenses and a trusted store receipt clock."""

    async def register_xray_policy(
        self,
        principal: Principal,
        account_id: str,
        registration: XrayPolicyRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt: ...

    async def register_entity_evidence(
        self,
        principal: Principal,
        registration: EntityEvidenceRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt: ...

    async def register_fund_definition(
        self,
        principal: Principal,
        registration: FundDefinitionRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt: ...

    async def register_fund_mapping(
        self,
        principal: Principal,
        registration: FundSourceMappingRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt: ...

    async def ingest_classifications(
        self,
        principal: Principal,
        request: ClassificationRequest,
        pages: tuple[ClassificationPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt: ...

    async def ingest_constituents(
        self,
        principal: Principal,
        request: ConstituentRequest,
        pages: tuple[ConstituentPage, ...],
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt: ...
