"""Real PostgreSQL differential proof against the unchanged scalar physical gate."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Table, event, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session
from trading212_application import reports as app
from trading212_domain.reports import ReportSourceUse
from trading212_persistence import report_sources as sources
from trading212_persistence.source_models import SourceExpiryEventModel, SourceRetentionWorkModel
from trading212_persistence.source_retention import SourcePurgeBudget
from trading212_persistence.source_retention_service import SOURCE_PAYLOADS, _expire_snapshot
from trading212_persistence.xray_catalog_models import (
    ConstituentHoldingModel,
    ConstituentSnapshotModel,
    XrayEvidenceFields,
)
from trading212_persistence.xray_enrichment_retention import _expire_enrichment_source
from trading212_persistence.xray_lifecycle_models import (
    EnrichmentExpiryEventModel,
    EnrichmentRetentionWorkModel,
)
from trading212_persistence.xray_run_models import XrayInputDependencyModel, XrayRunModel
from trading212_security.principals import AuthorizationError

from tests.integration.acquired_research_report_case import AcquiredResearchReportCase
from tests.integration.acquired_research_report_case import (
    acquired_research_report_case as acquired_research_report_case,
)
from tests.integration.research_case import research_case as research_case
from tests.integration.research_report_case import generate, selection
from tests.integration.research_report_case import research_report_case as research_report_case
from tests.integration.test_acquired_research_reports_postgres import (
    _authority_revision,
    _no_private_reads,
    _report_state,
)
from tests.integration.test_xray_reads_postgres import XrayReadCase, company
from tests.integration.test_xray_reads_postgres import xray_read_case as xray_read_case

pytestmark = pytest.mark.integration


@contextmanager
def _metadata_selects_only(engine: Engine) -> Iterator[None]:
    def before(
        _connection: Connection,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _many: bool,
    ) -> None:
        sql = statement.lower().lstrip()
        if sql.startswith("select"):
            assert not any(
                token in sql
                for token in (
                    "canonical_",
                    "metadata_json",
                    ".payload",
                    ".contents",
                    ".rate",
                )
            ), "A physical authority query selected private payload."

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", before)


def _allowed(call: Callable[[], None]) -> bool:
    try:
        call()
    except AuthorizationError:
        return False
    return True


def _differential(
    session: Session,
    *,
    owner: UUID,
    family: str,
    identifiers: tuple[UUID, ...],
    at: datetime,
    use: ReportSourceUse,
    expected: bool,
) -> None:
    model = sources._PHYSICAL[family][0]

    def scalar() -> None:
        for identifier in identifiers:
            row = cast(
                sources.PhysicalSource | None,
                session.scalar(
                    select(model).where(model.owner_id == owner, model.id == identifier)
                ),
            )
            if row is None:
                raise AuthorizationError("access denied")
            sources._physical_permit(session, row, family, source_use=use, now=at)

    original = _allowed(scalar)
    candidate = sources._physical_permit_many
    engine = session.get_bind()
    assert isinstance(engine, Engine)
    with _metadata_selects_only(engine):
        batched = _allowed(
            lambda: candidate(
                session,
                owner_id=owner,
                family=family,
                source_ids=identifiers,
                source_use=use,
                now=at,
            )
        )
    assert original is batched is expected


async def test_real_parent_families_match_scalar_expiry_markers_and_ownership(
    xray_read_case: XrayReadCase,
) -> None:
    case = xray_read_case
    saved = await company(case)
    owner = UUID(case.principal.owner_id)
    at = case.now[0]
    visited = set()
    with case.sessions() as session, session.begin():
        run = session.get_one(XrayRunModel, UUID(saved.context.run_id))
        for family in (
            "constituent",
            "classification",
            "entity_evidence",
            "fund_definition",
            "fund_mapping",
        ):
            model, column = sources._PHYSICAL[family]
            identifiers = tuple(
                session.scalars(
                    select(getattr(XrayInputDependencyModel, column))
                    .where(
                        XrayInputDependencyModel.owner_id == owner,
                        XrayInputDependencyModel.input_id == run.input_id,
                        getattr(XrayInputDependencyModel, column).is_not(None),
                    )
                    .distinct()
                )
            )
            assert identifiers
            visited.add(family)
            identifier = identifiers[0]
            source = cast(sources.PhysicalSource, session.get_one(model, identifier))
            for use in (ReportSourceUse.REPORT, ReportSourceUse.EXPORT):
                _differential(
                    session,
                    owner=owner,
                    family=family,
                    identifiers=identifiers,
                    at=at,
                    use=use,
                    expected=True,
                )
            for selected_owner, ids in (
                (owner, (identifier, uuid4())),
                (uuid4(), (identifier,)),
            ):
                _differential(
                    session,
                    owner=selected_owner,
                    family=family,
                    identifiers=ids,
                    at=at,
                    use=ReportSourceUse.REPORT,
                    expected=False,
                )
            _differential(
                session,
                owner=owner,
                family=family,
                identifiers=(identifier,),
                at=source.expires_at,
                use=ReportSourceUse.REPORT,
                expected=False,
            )
            physical = family == "constituent"
            expiry_model = SourceExpiryEventModel if physical else EnrichmentExpiryEventModel
            work_model = SourceRetentionWorkModel if physical else EnrichmentRetentionWorkModel
            # The database forbids invented expiry events or direct complete
            # markers. Exercise the real pending-to-complete lifecycle, including
            # copied/private payload drain, inside a rolled-back savepoint.
            # Its expiry instant is explicit; the source header and the original
            # fixture clock remain unchanged. Scalar authority denies a physical
            # marker even when an analytical cutoff predates that marker.
            retention_at = source.expires_at + timedelta(microseconds=1)
            with session.begin_nested() as nested:
                work_fields = (
                    {"removed_observation_count": 0} if physical else {"removed_row_count": 0}
                )
                work = work_model(
                    id=uuid4(),
                    owner_id=owner,
                    **{column: identifier},
                    content_digest=source.content_digest,
                    created_at=retention_at,
                    started_at=retention_at,
                    phase="copies",
                    completed_at=None,
                    **work_fields,
                )
                session.add(work)
                session.flush()
                assert (
                    session.scalar(
                        select(expiry_model.id).where(
                            expiry_model.owner_id == owner,
                            getattr(expiry_model, column) == identifier,
                        )
                    )
                    is None
                )
                _differential(
                    session,
                    owner=owner,
                    family=family,
                    identifiers=identifiers,
                    at=at,
                    use=ReportSourceUse.REPORT,
                    expected=False,
                )
                for _ in range(64):
                    budget = SourcePurgeBudget()
                    if physical:
                        assert isinstance(source, ConstituentSnapshotModel)
                        columns = next(
                            columns
                            for parent, _child, columns in SOURCE_PAYLOADS
                            if parent is ConstituentSnapshotModel
                        )
                        _expire_snapshot(
                            session,
                            source,
                            cast(Table, ConstituentHoldingModel.__table__),
                            columns,
                            at=retention_at,
                            budget=budget,
                        )
                    else:
                        _expire_enrichment_source(
                            session,
                            cast(XrayEvidenceFields, source),
                            column,
                            retention_at,
                            budget,
                        )
                    session.flush()
                    if work.phase == "complete":
                        break
                else:
                    pytest.fail(
                        "Guarded physical source cleanup exceeded64 normal bounded invocations"
                    )
                expired = session.scalar(
                    select(expiry_model).where(
                        expiry_model.owner_id == owner,
                        getattr(expiry_model, column) == identifier,
                    )
                )
                assert expired is not None
                assert work.completed_at == retention_at
                # Completed source lifecycle legally retains both the expiry event
                # and its work marker. No isolated-event/complete-work state is
                # fabricated to bypass the exact database guards.
                _differential(
                    session,
                    owner=owner,
                    family=family,
                    identifiers=identifiers,
                    at=at,
                    use=ReportSourceUse.REPORT,
                    expected=False,
                )
                nested.rollback()
            _differential(
                session,
                owner=owner,
                family=family,
                identifiers=identifiers,
                at=at,
                use=ReportSourceUse.REPORT,
                expected=True,
            )
    assert visited == {
        "constituent",
        "classification",
        "entity_evidence",
        "fund_definition",
        "fund_mapping",
    }


async def test_real_acquired_fx_uses_and_fresh_revocation_match_scalar_before_private_reads(
    acquired_research_report_case: AcquiredResearchReportCase,
) -> None:
    case = acquired_research_report_case
    report = case.report
    owner = UUID(report.research.xray.principal.owner_id)
    identifier = UUID(case.fx.id)
    with report.research.xray.sessions() as session, session.begin():
        for use, expected in ((ReportSourceUse.REPORT, True), (ReportSourceUse.EXPORT, False)):
            _differential(
                session,
                owner=owner,
                family="fx",
                identifiers=(identifier,),
                at=report.research.xray.now[0],
                use=use,
                expected=expected,
            )
    # Append a real immutable grant revision; neither the function nor its
    # entitlement inputs are replaced. The next call must see fresh metadata.
    _authority_revision(case, "grant_report")
    with report.research.xray.sessions() as session, session.begin():
        _differential(
            session,
            owner=owner,
            family="fx",
            identifiers=(identifier,),
            at=report.research.xray.now[0],
            use=ReportSourceUse.REPORT,
            expected=False,
        )
    before = _report_state(case)
    with _no_private_reads(case), pytest.raises(app.ReportServiceError):
        await generate(report, selected=selection(report))
    assert _report_state(case) == before
