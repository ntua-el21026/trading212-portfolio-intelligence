"""PostgreSQL admission and immutability regressions; fixtures do not execute finance."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, delete, insert, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from trading212_persistence.premium_models import PremiumCapacityModel
from trading212_persistence.risk_models import RiskDefinitionModel, RiskVersionModel
from trading212_persistence.scenario_models import (
    ScenarioDefinitionModel,
    ScenarioShockModel,
    ScenarioVersionModel,
)
from trading212_persistence.scenario_source_models import (
    ScenarioSensitivityEvidenceLinkModel,
    ScenarioSensitivityEvidenceModel,
    ScenarioSensitivityEvidencePayloadModel,
    ScenarioSensitivityRetentionModel,
    ScenarioSensitivitySetModel,
    ScenarioSensitivityVersionModel,
    ScenarioSensitivityVersionPayloadModel,
)
from trading212_persistence.source_models import (
    MarketDataProviderModel,
    ProviderLicenseVersionModel,
)

from tests.integration import test_phase3_risk_schema as risk_schema
from tests.integration.test_migrations import _add_identity_graph
from tests.integration.test_migrations import database_engine as database_engine
from tests.integration.test_phase3_risk_schema import version as risk_version

risk_scope = risk_schema.scope  # Register the differently named shared pytest fixture.

pytestmark = [pytest.mark.integration, pytest.mark.migrations]
NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


@pytest.fixture
def scope(database_engine: Engine) -> Iterator[tuple[Session, UUID, UUID, UUID]]:
    with Session(database_engine) as session:
        owner, _, account, instrument, _, _ = _add_identity_graph(session)
        session.add(
            PremiumCapacityModel(
                owner_id=owner,
                reserved_bytes=0,
                retained_bytes=0,
                active_jobs=0,
                definition_versions=0,
                updated_at=NOW,
            )
        )
        session.flush()
        try:
            yield session, owner, account, instrument
        finally:
            session.rollback()


def definition(
    session: Session, owner: UUID, account: UUID, *, shocks: int = 0
) -> ScenarioVersionModel:
    row = ScenarioDefinitionModel(
        id=uuid4(),
        owner_id=owner,
        account_id=account,
        name="Synthetic scenario",
        revision=1,
        archived=False,
        created_at=NOW,
        updated_at=NOW,
    )
    session.add(row)
    session.flush()
    version = ScenarioVersionModel(
        id=uuid4(),
        owner_id=owner,
        account_id=account,
        definition_id=row.id,
        version_number=1,
        predecessor_id=None,
        name=row.name,
        description="Schema fixture",
        mode="first_order",
        method_version="1.0.0",
        content_digest="a" * 64,
        shock_count=shocks,
        exclusion_count=0,
        sealed=False,
        created_at=NOW,
    )
    session.add(version)
    session.flush()
    return version


def source(
    session: Session,
    owner: UUID,
    *,
    observation_count: int = 0,
    evidence_count: int = 0,
    invalid_equivalence: bool = False,
) -> tuple[ScenarioSensitivityVersionModel, ScenarioSensitivityVersionPayloadModel]:
    provider = MarketDataProviderModel(
        id=uuid4(),
        owner_id=owner,
        freshness_policy_version=None,
        max_age_seconds=None,
        capabilities=[],
        supported_price_bases=[],
        key=uuid4().hex,
        name="Synthetic sensitivity fixture",
        adapter_version="1",
        configuration_state="configured",
        synthetic=True,
        revision=1,
        updated_at=NOW,
        created_at=NOW,
    )
    session.add(provider)
    session.flush()
    license = ProviderLicenseVersionModel(
        id=uuid4(),
        owner_id=owner,
        provider_id=provider.id,
        version_number=1,
        version="1",
        effective_at=NOW,
        store_permission="allowed",
        display_permission="allowed",
        report_permission="allowed",
        export_permission="allowed",
        retention_days=7,
        attribution="Synthetic",
        evidence_key="synthetic",
        created_at=NOW,
    )
    session.add(license)
    session.flush()
    catalog = ScenarioSensitivitySetModel(
        id=uuid4(), owner_id=owner, provider_id=provider.id, created_at=NOW
    )
    session.add(catalog)
    session.flush()
    version = ScenarioSensitivityVersionModel(
        id=uuid4(),
        owner_id=owner,
        source_set_id=catalog.id,
        provider_id=provider.id,
        license_version_id=license.id,
        content_digest="b" * 64,
        driver_id=uuid4(),
        driver_definition_version_id=uuid4(),
        driver_definition_digest="c" * 64,
        revision=1,
        observation_count=observation_count,
        membership_count=0,
        evidence_count=evidence_count,
        expires_at=NOW + timedelta(days=7),
        sealed=False,
        created_at=NOW,
    )
    session.add(version)
    session.flush()
    payload = ScenarioSensitivityVersionPayloadModel(
        id=uuid4(),
        owner_id=owner,
        version_id=version.id,
        driver_kind="factor",
        shock_unit="simple_factor_return",
        equivalence_kind="unknown" if invalid_equivalence else "factor",
        equivalence_factor_id=uuid4(),
        equivalence_reason="unknown_driver_equivalence" if invalid_equivalence else None,
        effective_at=NOW,
        first_known_at=NOW,
        valid_from=NOW,
        valid_until=None,
        revision=1,
        adapter_id="synthetic",
        adapter_version="1",
        availability="unavailable",
        quality="partial",
        canonical_payload=b"synthetic schema fixture; not a calculator input",
        created_at=NOW,
    )
    session.add(payload)
    session.flush()
    return version, payload


def test_definition_publication_requires_exact_children_and_seal(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, account, _ = scope
    version = definition(session, owner, account, shocks=1)
    version.sealed = True
    session.flush()
    with (
        pytest.raises(IntegrityError, match="Scenario assumption publication incomplete"),
        session.begin_nested(),
    ):
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_definition_and_source_headers_publish_without_provider_payload_in_definition(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, account, _ = scope
    catalog, payload = source(session, owner)
    catalog.sealed = True
    session.flush()
    version = definition(session, owner, account, shocks=1)
    session.add(
        ScenarioShockModel(
            id=uuid4(),
            owner_id=owner,
            account_id=account,
            version_id=version.id,
            rule_key="shock:" + "d" * 64,
            kind="factor",
            size=Decimal("0.012345678901234567"),
            source_version_id=catalog.id,
            source_version_digest=catalog.content_digest,
            driver_id=catalog.driver_id,
            driver_definition_version_id=catalog.driver_definition_version_id,
            created_at=NOW,
        )
    )
    session.flush()
    version.sealed = True
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    with pytest.raises(IntegrityError, match="immutable"), session.begin_nested():
        session.execute(
            update(ScenarioVersionModel)
            .where(ScenarioVersionModel.id == version.id)
            .values(description="Changed")
        )
    with pytest.raises(IntegrityError, match="immutable"), session.begin_nested():
        session.execute(
            delete(ScenarioSensitivityVersionPayloadModel).where(
                ScenarioSensitivityVersionPayloadModel.id == payload.id
            )
        )
    stored = session.scalar(
        select(ScenarioShockModel).where(ScenarioShockModel.version_id == version.id)
    )
    assert stored is not None and stored.size == Decimal("0.012345678901234567")


def test_same_price_selector_cannot_be_repeated_with_a_different_size(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, account, instrument = scope
    version = definition(session, owner, account, shocks=2)

    def shock(key: str, size: str) -> ScenarioShockModel:
        return ScenarioShockModel(
            id=uuid4(),
            owner_id=owner,
            account_id=account,
            version_id=version.id,
            rule_key="shock:" + key * 64,
            kind="price",
            selector_kind="instrument",
            instrument_id=instrument,
            size=Decimal(size),
            created_at=NOW,
        )

    session.add(shock("d", "-0.25"))
    session.flush()
    with pytest.raises(IntegrityError, match="uq_scenario_shock_selector"), session.begin_nested():
        session.add(shock("e", "-0.5"))
        session.flush()


def test_unknown_driver_equivalence_cannot_carry_a_hidden_factor_identity(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, _, _ = scope
    with pytest.raises(IntegrityError, match="equivalence_identity"), session.begin_nested():
        source(session, owner, invalid_equivalence=True)


def test_sensitivity_versions_require_exact_membership_counts(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, _, _ = scope
    version, _ = source(session, owner, observation_count=1)
    version.sealed = True
    session.flush()
    with (
        pytest.raises(IntegrityError, match="Sensitivity source publication incomplete"),
        session.begin_nested(),
    ):
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_scenario_scope_cannot_cross_owner_accounts(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, _, account, _ = scope
    other, *_ = _add_identity_graph(session)
    with (
        pytest.raises(IntegrityError, match="Scenario account scope mismatch"),
        session.begin_nested(),
    ):
        session.add(
            ScenarioDefinitionModel(
                id=uuid4(),
                owner_id=other,
                account_id=account,
                name="Forbidden",
                revision=1,
                archived=False,
                updated_at=NOW,
                created_at=NOW,
            )
        )
        session.flush()


def test_source_payload_purge_preserves_definition_pin_and_blocks_reinsertion(
    scope: tuple[Session, UUID, UUID, UUID],
) -> None:
    session, owner, account, _ = scope
    catalog, payload = source(session, owner)
    catalog.sealed = True
    session.flush()
    version = definition(session, owner, account, shocks=1)
    session.add(
        ScenarioShockModel(
            id=uuid4(),
            owner_id=owner,
            account_id=account,
            version_id=version.id,
            rule_key="shock:" + "f" * 64,
            kind="factor",
            size=Decimal("0.01"),
            source_version_id=catalog.id,
            source_version_digest=catalog.content_digest,
            driver_id=catalog.driver_id,
            driver_definition_version_id=catalog.driver_definition_version_id,
            created_at=NOW,
        )
    )
    session.flush()
    version.sealed = True
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    marker = ScenarioSensitivityRetentionModel(
        id=uuid4(),
        owner_id=owner,
        version_id=catalog.id,
        reason="source_expired",
        completed_at=None,
        created_at=NOW,
    )
    session.add(marker)
    session.flush()
    with pytest.raises(IntegrityError, match="copies remain"), session.begin_nested():
        session.execute(
            update(ScenarioSensitivityRetentionModel)
            .where(ScenarioSensitivityRetentionModel.id == marker.id)
            .values(completed_at=NOW + timedelta(days=1))
        )
    session.execute(
        delete(ScenarioSensitivityVersionPayloadModel).where(
            ScenarioSensitivityVersionPayloadModel.id == payload.id
        )
    )
    marker.completed_at = NOW + timedelta(days=1)
    session.flush()
    assert session.get(ScenarioSensitivityVersionModel, catalog.id) is not None
    assert (
        session.scalar(
            select(ScenarioShockModel.source_version_id).where(
                ScenarioShockModel.version_id == version.id
            )
        )
        == catalog.id
    )
    assert (
        session.scalar(
            select(ScenarioSensitivityVersionPayloadModel.id).where(
                ScenarioSensitivityVersionPayloadModel.version_id == catalog.id
            )
        )
        is None
    )

    with pytest.raises(IntegrityError, match="sealed or restricted"), session.begin_nested():
        session.add(
            ScenarioSensitivityVersionPayloadModel(
                id=uuid4(),
                owner_id=owner,
                version_id=catalog.id,
                driver_kind="factor",
                shock_unit="simple_factor_return",
                equivalence_kind="factor",
                equivalence_factor_id=uuid4(),
                effective_at=NOW,
                first_known_at=NOW,
                valid_from=NOW,
                valid_until=None,
                revision=1,
                adapter_id="synthetic",
                adapter_version="1",
                availability="unavailable",
                quality="partial",
                canonical_payload=b"forbidden source reinsertion",
                created_at=NOW,
            )
        )
        session.flush()


@pytest.mark.parametrize("last_family", ("risk", "scenario"))
def test_definition_version_capacity_is_shared_across_families(
    risk_scope: tuple[Session, UUID, UUID, UUID, UUID],
    last_family: str,
) -> None:
    session, owner, account, _, calendar = risk_scope
    _, prototype = risk_version(session, owner, account, calendar)
    # 511 actual risk versions plus one scenario version exhaust the same owner cap.
    definition_ids = [uuid4() for _ in range(510)]
    session.execute(
        insert(RiskDefinitionModel),
        [
            dict(
                id=identity,
                owner_id=owner,
                account_id=account,
                name="Risk",
                revision=1,
                archived=False,
                created_at=NOW,
                updated_at=NOW,
            )
            for identity in definition_ids
        ],
    )
    values = {
        column.name: getattr(prototype, column.name) for column in RiskVersionModel.__table__.c
    }
    session.execute(
        insert(RiskVersionModel),
        [dict(values, id=uuid4(), definition_id=identity) for identity in definition_ids],
    )
    saved = definition(session, owner, account)
    saved.sealed = True
    session.flush()
    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    with (
        pytest.raises(IntegrityError, match="Premium version capacity unavailable"),
        session.begin_nested(),
    ):
        if last_family == "scenario":
            definition(session, owner, account)
        else:
            risk_version(session, owner, account, calendar)


def test_scenario_retention_cannot_be_inserted_already_completed(
    risk_scope: tuple[Session, UUID, UUID, UUID, UUID],
) -> None:
    session, owner, account, principal, _ = risk_scope
    root, command = uuid4(), uuid4()
    # An unpublished root prefix isolates the immediate marker constraint; this
    # fixture rolls back and never claims successful financial publication.
    session.execute(
        text("""
        INSERT INTO application_command_identities
        (id,owner_id,account_id,command,idempotency_key,command_digest,premium_resource_id,
         premium_actor_id,premium_correlation_id,created_at)
        VALUES (:command,:owner,:account,'scenario.run.create.v1',:key,:digest,:root,
                :principal,'schema',:now)
    """),
        dict(
            command=command,
            owner=owner,
            account=account,
            key=str(command),
            digest="a" * 64,
            root=root,
            principal=principal,
            now=NOW,
        ),
    )
    session.execute(
        text("""
        INSERT INTO premium_runs
        (id,owner_id,account_id,kind,command_id,actor_principal_id,input_digest,expires_at,
         method_version,schema_version,numerical_profile,reserved_bytes,retained_bytes,created_at)
        VALUES (:root,:owner,:account,'scenario',:command,:principal,:digest,:expiry,
                '1.0.0','1.0.0','premium_decimal96_q18_v1',33554432,0,:now)
    """),
        dict(
            root=root,
            owner=owner,
            account=account,
            command=command,
            principal=principal,
            digest="b" * 64,
            expiry=NOW + timedelta(days=1),
            now=NOW,
        ),
    )
    with (
        pytest.raises(IntegrityError, match="Scenario retention cannot begin completed"),
        session.begin_nested(),
    ):
        session.execute(
            text("""
            INSERT INTO premium_retention_events
            (id,owner_id,account_id,run_id,reason,completed_at,created_at)
            VALUES (:id,:owner,:account,:root,'source_restricted',:now,:now)
        """),
            dict(id=uuid4(), owner=owner, account=account, root=root, now=NOW),
        )


def test_shared_evidence_publication_serializes_with_physical_purge(
    database_engine: Engine,
) -> None:
    with Session(database_engine) as setup:
        owner, _, _, _, _, _ = _add_identity_graph(setup)
        v1, _ = source(setup, owner, evidence_count=1)
        evidence = ScenarioSensitivityEvidenceModel(
            id=uuid4(),
            owner_id=owner,
            provider_id=v1.provider_id,
            license_version_id=v1.license_version_id,
            source_record_id=uuid4(),
            content_digest="e" * 64,
            created_at=NOW,
        )
        setup.add(evidence)
        setup.flush()
        physical = ScenarioSensitivityEvidencePayloadModel(
            id=uuid4(),
            owner_id=owner,
            evidence_id=evidence.id,
            effective_at=NOW,
            first_known_at=NOW,
            adapter_id="synthetic",
            adapter_version="1",
            transformation="identity_local_simple_return_v1",
            canonical_payload=b"synthetic evidence; schema test only",
            created_at=NOW,
        )
        setup.add(physical)
        setup.flush()
        setup.add(
            ScenarioSensitivityEvidenceLinkModel(
                id=uuid4(),
                owner_id=owner,
                version_id=v1.id,
                evidence_id=evidence.id,
                observation_id=None,
                created_at=NOW,
            )
        )
        setup.flush()
        v1.sealed = True
        setup.flush()
        version_id, evidence_id, payload_id = v1.id, evidence.id, physical.id
        setup.commit()
        setup.add(
            ScenarioSensitivityRetentionModel(
                id=uuid4(),
                owner_id=owner,
                version_id=version_id,
                reason="source_restricted",
                completed_at=None,
                created_at=NOW,
            )
        )
        setup.commit()
    with Session(database_engine) as publisher, Session(database_engine) as purger:
        v2, _ = source(publisher, owner, evidence_count=1)
        purger.execute(
            delete(ScenarioSensitivityEvidencePayloadModel).where(
                ScenarioSensitivityEvidencePayloadModel.id == payload_id
            )
        )
        publisher.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError) as failure:
            publisher.add(
                ScenarioSensitivityEvidenceLinkModel(
                    id=uuid4(),
                    owner_id=owner,
                    version_id=v2.id,
                    evidence_id=evidence_id,
                    observation_id=None,
                    created_at=NOW,
                )
            )
            publisher.flush()
        assert getattr(failure.value.orig, "sqlstate", None) == "55P03"
        publisher.rollback()
        purger.commit()
    with Session(database_engine) as retry:
        v3, _ = source(retry, owner, evidence_count=1)
        with pytest.raises(IntegrityError, match="Sensitivity evidence payload unavailable"):
            retry.add(
                ScenarioSensitivityEvidenceLinkModel(
                    id=uuid4(),
                    owner_id=owner,
                    version_id=v3.id,
                    evidence_id=evidence_id,
                    observation_id=None,
                    created_at=NOW,
                )
            )
            retry.flush()
        retry.rollback()


def test_source_purge_owner_contention_fails_before_waiting_with_payload_tuple(
    database_engine: Engine,
) -> None:
    with Session(database_engine) as setup:
        owner, *_ = _add_identity_graph(setup)
        version, payload = source(setup, owner)
        version.sealed = True
        setup.flush()
        version_id, payload_id = version.id, payload.id
        setup.commit()
        setup.add(
            ScenarioSensitivityRetentionModel(
                id=uuid4(),
                owner_id=owner,
                version_id=version_id,
                reason="source_restricted",
                completed_at=None,
                created_at=NOW,
            )
        )
        setup.commit()
    with Session(database_engine) as holder, Session(database_engine) as purger:
        holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"sources:{owner}"},
        )
        purger.execute(text("SET LOCAL lock_timeout = '1s'"))
        with pytest.raises(
            OperationalError, match="Sensitivity source purge owner is busy"
        ) as failure:
            purger.execute(
                delete(ScenarioSensitivityVersionPayloadModel).where(
                    ScenarioSensitivityVersionPayloadModel.id == payload_id
                )
            )
        assert getattr(failure.value.orig, "sqlstate", None) == "55P03"
        purger.rollback()
        holder.execute(
            delete(ScenarioSensitivityVersionPayloadModel).where(
                ScenarioSensitivityVersionPayloadModel.id == payload_id
            )
        )
        holder.commit()
