"""Private transactional scenario definitions using shared premium authority and capacity."""

from dataclasses import replace
from hashlib import sha256
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from trading212_application.targets import validate_target_idempotency_key
from trading212_domain.errors import DomainError
from trading212_domain.scenario import (
    ScenarioComponentSelector,
    ScenarioCurrencySelector,
    ScenarioEntitySelector,
    ScenarioExclusion,
    ScenarioFactorShock,
    ScenarioFxShock,
    ScenarioInstrumentSelector,
    ScenarioPriceSelector,
    ScenarioPriceShock,
    ScenarioRateShock,
    ScenarioRegionSelector,
    ScenarioSectorSelector,
    ScenarioSensitivityVersionPin,
    ScenarioShock,
    ScenarioVersionContent,
    scenario_exclusion_key,
    scenario_rule_key,
)
from trading212_domain.scenario_serialization import (
    scenario_definition_digest,
    scenario_record_bytes,
)
from trading212_domain.sources import SourceUse
from trading212_domain.values import CurrencyCode, require_bounded_text
from trading212_security.principals import Scope

from .premium_models import (
    PremiumAuditModel,
    PremiumCapacityModel,
    PremiumJobModel,
    PremiumOwned,
    PremiumRunModel,
)
from .report_authorization import ReportAuthorization
from .report_models import ApplicationCommandIdentityModel
from .risk_models import RiskVersionModel
from .scenario_models import (
    ScenarioDefinitionModel,
    ScenarioExclusionModel,
    ScenarioShockModel,
    ScenarioVersionModel,
)
from .scenario_source_models import (
    ScenarioSensitivityRetentionModel,
    ScenarioSensitivityVersionModel,
)
from .scenario_source_store import ScenarioSourceStore
from .scenario_store_types import (
    ScenarioStorageError,
    StoredScenarioDefinition,
    StoredScenarioVersion,
)
from .scenario_store_types import (
    ScenarioStorageErrorCode as Code,
)
from .xray_catalog_models import EconomicEntityModel, XrayTaxonomyModel

READ_SCOPES = frozenset((Scope.PORTFOLIO_READ, Scope.ANALYTICS_READ))
WRITE_SCOPES = READ_SCOPES | {Scope.SCENARIOS_WRITE}


def scenario_owner_lock(session: Session, owner: UUID) -> None:
    for namespace in ("sources", "xray", "historical", "premium"):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"{namespace}:{owner}"},
        )


def selector_fields(selector: ScenarioComponentSelector | None) -> dict[str, object]:
    fields: dict[str, object] = {
        name: None
        for name in (
            "selector_kind",
            "instrument_id",
            "entity_id",
            "taxonomy_id",
            "taxonomy_version",
            "bucket_key",
            "currency",
        )
    }
    if selector is None:
        return fields
    fields["selector_kind"] = selector.kind
    if isinstance(selector, ScenarioInstrumentSelector):
        fields["instrument_id"] = selector.instrument_id
    elif isinstance(selector, ScenarioEntitySelector):
        fields["entity_id"] = selector.entity_id
    elif isinstance(selector, ScenarioCurrencySelector):
        fields["currency"] = selector.currency.value
    elif isinstance(selector, (ScenarioSectorSelector, ScenarioRegionSelector)):
        fields.update(
            taxonomy_id=selector.taxonomy_id,
            taxonomy_version=selector.taxonomy_version,
            bucket_key=selector.bucket_key,
        )
    return fields


def read_selector(row: ScenarioShockModel | ScenarioExclusionModel) -> ScenarioComponentSelector:
    if row.selector_kind == "instrument":
        return ScenarioInstrumentSelector(instrument_id=cast(UUID, row.instrument_id))
    if row.selector_kind == "entity":
        return ScenarioEntitySelector(entity_id=cast(UUID, row.entity_id))
    if row.selector_kind == "economic_currency":
        return ScenarioCurrencySelector(currency=CurrencyCode(cast(str, row.currency)))
    if row.selector_kind == "sector":
        return ScenarioSectorSelector(
            taxonomy_id=cast(UUID, row.taxonomy_id),
            taxonomy_version=cast(str, row.taxonomy_version),
            bucket_key=cast(str, row.bucket_key),
        )
    if row.selector_kind == "region":
        return ScenarioRegionSelector(
            taxonomy_id=cast(UUID, row.taxonomy_id),
            taxonomy_version=cast(str, row.taxonomy_version),
            bucket_key=cast(str, row.bucket_key),
        )
    raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)


class ScenarioDefinitionStore(ScenarioSourceStore):
    def authority(
        self, session: Session, auth: ReportAuthorization, *, write: bool = False
    ) -> ReportAuthorization:
        auth = replace(
            auth, required_scopes=auth.required_scopes | (WRITE_SCOPES if write else READ_SCOPES)
        )
        auth.check(session, now=self._now())
        scenario_owner_lock(session, auth.owner_id)
        return auth

    def _owned[M: PremiumOwned](
        self, session: Session, auth: ReportAuthorization, model: type[M], identifier: UUID
    ) -> M:
        row = session.scalar(
            select(model).where(
                model.id == identifier,
                model.owner_id == auth.owner_id,
                model.account_id == auth.account_id,
            )
        )
        if row is None:
            raise ScenarioStorageError(Code.NOT_FOUND)
        return row

    def capacity(self, session: Session, auth: ReportAuthorization) -> PremiumCapacityModel:
        session.execute(
            insert(PremiumCapacityModel)
            .values(
                owner_id=auth.owner_id,
                reserved_bytes=0,
                retained_bytes=0,
                active_jobs=0,
                definition_versions=0,
                updated_at=self._now(),
            )
            .on_conflict_do_nothing(index_elements=["owner_id"])
        )
        row = session.scalar(
            select(PremiumCapacityModel)
            .where(PremiumCapacityModel.owner_id == auth.owner_id)
            .with_for_update()
        )
        if row is None:
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        return row

    def reserve_run_capacity(self, session: Session, auth: ReportAuthorization) -> None:
        """Caller must atomically create one root/job/outbox or roll back this reservation."""
        auth = self.authority(session, auth, write=True)
        capacity = self.capacity(session, auth)
        active = (
            session.scalar(
                select(func.count())
                .select_from(PremiumJobModel)
                .where(
                    PremiumJobModel.owner_id == auth.owner_id,
                    PremiumJobModel.state.in_(("queued", "running")),
                )
            )
            or 0
        )
        actual = (
            session.scalar(
                select(
                    func.coalesce(
                        func.sum(PremiumRunModel.reserved_bytes + PremiumRunModel.retained_bytes), 0
                    )
                ).where(PremiumRunModel.owner_id == auth.owner_id)
            )
            or 0
        )
        if (
            max(active, capacity.active_jobs) >= 2
            or max(actual, capacity.reserved_bytes + capacity.retained_bytes) + 33554432 > 268435456
        ):
            raise ScenarioStorageError(Code.RATE_LIMITED)
        capacity.active_jobs += 1
        capacity.reserved_bytes += 33554432
        capacity.updated_at = self._now()
        session.flush()

    def prior_command(
        self, session: Session, auth: ReportAuthorization, command: str, key: str, digest: str
    ) -> ApplicationCommandIdentityModel | None:
        row = session.scalar(
            select(ApplicationCommandIdentityModel).where(
                ApplicationCommandIdentityModel.owner_id == auth.owner_id,
                ApplicationCommandIdentityModel.command == command,
                ApplicationCommandIdentityModel.idempotency_key == key,
            )
        )
        if row is not None and (row.account_id != auth.account_id or row.command_digest != digest):
            raise ScenarioStorageError(Code.CONFLICT)
        return row

    def command_identity(
        self,
        session: Session,
        auth: ReportAuthorization,
        command: Literal[
            "scenario.definition.create.v1",
            "scenario.version.create.v1",
            "scenario.run.create.v1",
            "scenario.run.cancel.v1",
        ],
        key: str,
        digest: str,
        resource: UUID,
        correlation_id: str,
    ) -> ApplicationCommandIdentityModel:
        validate_target_idempotency_key(key)
        require_bounded_text(correlation_id, field="correlation_id", maximum=120)
        row = ApplicationCommandIdentityModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            command=command,
            idempotency_key=key,
            command_digest=digest,
            premium_resource_id=resource,
            premium_actor_id=auth.principal_id,
            premium_correlation_id=correlation_id,
            report_job_id=None,
            export_job_id=None,
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        session.add(
            PremiumAuditModel(
                id=uuid4(),
                owner_id=auth.owner_id,
                account_id=auth.account_id,
                command_id=row.id,
                kind="cancelled" if command == "scenario.run.cancel.v1" else "created",
                created_at=self._now(),
            )
        )
        session.flush()
        return row

    def _validate_references(
        self, session: Session, auth: ReportAuthorization, content: ScenarioVersionContent
    ) -> None:
        sources = self.copy_authority()
        selectors: list[ScenarioComponentSelector] = [
            item.selector for item in content.shocks if isinstance(item, ScenarioPriceShock)
        ]
        selectors.extend(item.selector for item in content.exclusions)
        for selector in selectors:
            if (
                isinstance(selector, ScenarioEntitySelector)
                and session.scalar(
                    select(EconomicEntityModel.id).where(
                        EconomicEntityModel.id == selector.entity_id,
                        EconomicEntityModel.owner_id == auth.owner_id,
                    )
                )
                is None
            ):
                raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
            if isinstance(selector, (ScenarioSectorSelector, ScenarioRegionSelector)):
                taxonomy = session.scalar(
                    select(XrayTaxonomyModel).where(
                        XrayTaxonomyModel.id == selector.taxonomy_id,
                        XrayTaxonomyModel.owner_id == auth.owner_id,
                    )
                )
                if taxonomy is None or taxonomy.version != selector.taxonomy_version:
                    raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
        for shock in content.shocks:
            if not isinstance(shock, (ScenarioRateShock, ScenarioFactorShock)):
                continue
            pin = shock.source
            row = session.scalar(
                select(ScenarioSensitivityVersionModel).where(
                    ScenarioSensitivityVersionModel.id == pin.version_id,
                    ScenarioSensitivityVersionModel.owner_id == auth.owner_id,
                )
            )
            if (
                row is None
                or not row.sealed
                or row.expires_at <= self._now()
                or session.scalar(
                    select(ScenarioSensitivityRetentionModel.id).where(
                        ScenarioSensitivityRetentionModel.owner_id == auth.owner_id,
                        ScenarioSensitivityRetentionModel.version_id == pin.version_id,
                    )
                )
            ):
                raise ScenarioStorageError(Code.SOURCE_UNAVAILABLE)
            if (row.content_digest, row.driver_id, row.driver_definition_version_id) != (
                pin.content_digest,
                pin.driver_id,
                pin.driver_definition_version_id,
            ):
                raise ScenarioStorageError(Code.CONFLICT)
            sources._permit(session, auth.owner_id, row.license_version_id, SourceUse.DISPLAY)
        auth.check(session, now=self._now())

    def read_version(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> StoredScenarioVersion:
        auth = self.authority(session, auth)
        row = self._owned(session, auth, ScenarioVersionModel, identifier)
        if not row.sealed:
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        shocks = tuple(
            session.scalars(
                select(ScenarioShockModel)
                .where(
                    ScenarioShockModel.version_id == row.id,
                    ScenarioShockModel.owner_id == auth.owner_id,
                    ScenarioShockModel.account_id == auth.account_id,
                )
                .order_by(ScenarioShockModel.rule_key)
                .limit(129)
            )
        )
        exclusions = tuple(
            session.scalars(
                select(ScenarioExclusionModel)
                .where(
                    ScenarioExclusionModel.version_id == row.id,
                    ScenarioExclusionModel.owner_id == auth.owner_id,
                    ScenarioExclusionModel.account_id == auth.account_id,
                )
                .order_by(ScenarioExclusionModel.rule_key)
                .limit(129)
            )
        )
        if (
            len(shocks) != row.shock_count
            or len(exclusions) != row.exclusion_count
            or max(len(shocks), len(exclusions)) > 128
        ):
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        try:
            values: list[ScenarioShock] = []
            for item in shocks:
                shock: ScenarioShock
                if item.kind == "price":
                    shock = ScenarioPriceShock(
                        selector=cast(ScenarioPriceSelector, read_selector(item)), size=item.size
                    )
                elif item.kind == "fx":
                    shock = ScenarioFxShock(
                        selector=ScenarioCurrencySelector(
                            currency=CurrencyCode(cast(str, item.shock_currency))
                        ),
                        size=item.size,
                    )
                elif item.kind in ("rate", "factor"):
                    pin = ScenarioSensitivityVersionPin(
                        version_id=cast(UUID, item.source_version_id),
                        content_digest=cast(str, item.source_version_digest),
                        driver_id=cast(UUID, item.driver_id),
                        driver_definition_version_id=cast(UUID, item.driver_definition_version_id),
                    )
                    shock = (
                        ScenarioRateShock(source=pin, size=item.size)
                        if item.kind == "rate"
                        else ScenarioFactorShock(source=pin, size=item.size)
                    )
                else:
                    raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
                if scenario_rule_key(shock) != item.rule_key:
                    raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
                values.append(shock)
            excluded = tuple(ScenarioExclusion(selector=read_selector(item)) for item in exclusions)
            if any(
                scenario_exclusion_key(value) != item.rule_key
                for value, item in zip(excluded, exclusions, strict=True)
            ):
                raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
            content = ScenarioVersionContent(
                name=row.name,
                description=row.description,
                mode=cast(Literal["first_order", "compounded"], row.mode),
                shocks=tuple(values),
                exclusions=excluded,
            )
            if (
                content.method_version != row.method_version
                or scenario_definition_digest(content) != row.content_digest
            ):
                raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        except DomainError:
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE) from None
        auth.check(session, now=self._now())
        return StoredScenarioVersion(
            id=row.id,
            account_id=row.account_id,
            definition_id=row.definition_id,
            version_number=row.version_number,
            predecessor_id=row.predecessor_id,
            content=content,
            content_digest=row.content_digest,
            created_at=row.created_at,
        )

    def read_definition(
        self, session: Session, auth: ReportAuthorization, identifier: UUID
    ) -> StoredScenarioDefinition:
        auth = self.authority(session, auth)
        row = self._owned(session, auth, ScenarioDefinitionModel, identifier)
        version = session.scalar(
            select(ScenarioVersionModel.id).where(
                ScenarioVersionModel.definition_id == row.id,
                ScenarioVersionModel.owner_id == auth.owner_id,
                ScenarioVersionModel.account_id == auth.account_id,
                ScenarioVersionModel.version_number == row.revision,
                ScenarioVersionModel.sealed.is_(True),
            )
        )
        if version is None:
            raise ScenarioStorageError(Code.SCENARIO_UNAVAILABLE)
        auth.check(session, now=self._now())
        return StoredScenarioDefinition(
            id=row.id,
            account_id=row.account_id,
            name=row.name,
            revision=row.revision,
            archived=row.archived,
            current_version_id=version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _publish_version(
        self,
        session: Session,
        auth: ReportAuthorization,
        parent: ScenarioDefinitionModel,
        content: ScenarioVersionContent,
        predecessor: UUID | None,
    ) -> ScenarioVersionModel:
        capacity = self.capacity(session, auth)
        actual = sum(
            session.scalar(
                select(func.count()).select_from(model).where(model.owner_id == auth.owner_id)
            )
            or 0
            for model in (RiskVersionModel, ScenarioVersionModel)
        )
        if max(actual, capacity.definition_versions) >= 512:
            raise ScenarioStorageError(Code.RATE_LIMITED)
        capacity.definition_versions += 1
        capacity.updated_at = self._now()
        row = ScenarioVersionModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            definition_id=parent.id,
            version_number=parent.revision,
            predecessor_id=predecessor,
            name=content.name,
            description=content.description,
            mode=content.mode,
            method_version=content.method_version,
            content_digest=scenario_definition_digest(content),
            shock_count=len(content.shocks),
            exclusion_count=len(content.exclusions),
            sealed=False,
            created_at=self._now(),
        )
        session.add(row)
        session.flush()
        for shock in content.shocks:
            values: dict[str, object] = dict(
                shock_currency=None,
                source_version_id=None,
                source_version_digest=None,
                driver_id=None,
                driver_definition_version_id=None,
                **selector_fields(None),
            )
            if isinstance(shock, ScenarioPriceShock):
                values.update(selector_fields(shock.selector))
            elif isinstance(shock, ScenarioFxShock):
                values["shock_currency"] = shock.selector.currency.value
            else:
                values.update(
                    source_version_id=shock.source.version_id,
                    source_version_digest=shock.source.content_digest,
                    driver_id=shock.source.driver_id,
                    driver_definition_version_id=shock.source.driver_definition_version_id,
                )
            session.add(
                ScenarioShockModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    version_id=row.id,
                    rule_key=scenario_rule_key(shock),
                    kind=shock.kind,
                    size=shock.size,
                    created_at=self._now(),
                    **values,
                )
            )
        for exclusion in content.exclusions:
            session.add(
                ScenarioExclusionModel(
                    id=uuid4(),
                    owner_id=auth.owner_id,
                    account_id=auth.account_id,
                    version_id=row.id,
                    rule_key=scenario_exclusion_key(exclusion),
                    created_at=self._now(),
                    **selector_fields(exclusion.selector),
                )
            )
        session.flush()
        row.sealed = True
        session.flush()
        return row

    def publish_definition(
        self,
        session: Session,
        auth: ReportAuthorization,
        content: ScenarioVersionContent,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> StoredScenarioDefinition:
        auth = self.authority(session, auth, write=True)
        validate_target_idempotency_key(idempotency_key)
        require_bounded_text(correlation_id, field="correlation_id", maximum=120)
        digest = sha256(
            b"t212pi.command.scenario.definition.create.v1\0"
            + auth.account_id.bytes
            + scenario_record_bytes(content)
        ).hexdigest()
        prior = self.prior_command(
            session, auth, "scenario.definition.create.v1", idempotency_key, digest
        )
        if prior is not None:
            return self.read_definition(session, auth, cast(UUID, prior.premium_resource_id))
        self._validate_references(session, auth, content)
        self.capacity(session, auth)
        parent = ScenarioDefinitionModel(
            id=uuid4(),
            owner_id=auth.owner_id,
            account_id=auth.account_id,
            name=content.name,
            revision=1,
            archived=False,
            created_at=self._now(),
            updated_at=self._now(),
        )
        session.add(parent)
        session.flush()
        self._publish_version(session, auth, parent, content, None)
        self.command_identity(
            session,
            auth,
            "scenario.definition.create.v1",
            idempotency_key,
            digest,
            parent.id,
            correlation_id,
        )
        auth.check(session, now=self._now())
        return self.read_definition(session, auth, parent.id)

    def publish_version(
        self,
        session: Session,
        auth: ReportAuthorization,
        definition_id: UUID,
        expected_revision: int,
        content: ScenarioVersionContent,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> StoredScenarioVersion:
        auth = self.authority(session, auth, write=True)
        validate_target_idempotency_key(idempotency_key)
        require_bounded_text(correlation_id, field="correlation_id", maximum=120)
        if type(expected_revision) is not int or not 1 <= expected_revision <= 512:
            raise ScenarioStorageError(Code.VALIDATION_FAILED)
        digest = sha256(
            b"t212pi.command.scenario.version.create.v1\0"
            + auth.account_id.bytes
            + definition_id.bytes
            + str(expected_revision).encode("ascii")
            + b"\0"
            + scenario_record_bytes(content)
        ).hexdigest()
        prior = self.prior_command(
            session, auth, "scenario.version.create.v1", idempotency_key, digest
        )
        if prior is not None:
            return self.read_version(session, auth, cast(UUID, prior.premium_resource_id))
        self._validate_references(session, auth, content)
        parent = self._owned(session, auth, ScenarioDefinitionModel, definition_id)
        if parent.revision != expected_revision or parent.archived:
            raise ScenarioStorageError(Code.REVISION_MISMATCH)
        predecessor = self.read_definition(session, auth, parent.id).current_version_id
        parent.revision += 1
        parent.name = content.name
        parent.updated_at = self._now()
        row = self._publish_version(session, auth, parent, content, predecessor)
        self.command_identity(
            session,
            auth,
            "scenario.version.create.v1",
            idempotency_key,
            digest,
            row.id,
            correlation_id,
        )
        auth.check(session, now=self._now())
        return self.read_version(session, auth, row.id)
