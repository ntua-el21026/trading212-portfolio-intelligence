"""Transactional authorized target commands and durable read projections."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from trading212_application import targets as app
from trading212_application.queries import CursorCodec
from trading212_application.views import Page
from trading212_domain import targets as domain
from trading212_domain.serialization import canonical_json
from trading212_domain.values import CurrencyCode, require_utc
from trading212_security.principals import Authorizer, Principal, Scope

from .collection_snapshots import (
    CollectionSnapshotDefinition,
    CollectionSnapshotResource,
    CollectionSnapshotStore,
    collection_filter_fingerprint,
)
from .models import (
    BrokerAccountModel,
    BrokerConnectionModel,
    CollectionQuerySnapshotMemberModel,
    InstrumentModel,
    ListingModel,
)
from .target_models import (
    TargetCollectionReferenceModel,
    TargetCommandIdentityModel,
    TargetConstraintModel,
    TargetExclusionModel,
    TargetHoldingModel,
    TargetMappingDecisionModel,
    TargetNodeModel,
    TargetNormalizationAdjustmentModel,
    TargetValidationIssueModel,
    TargetValidationResultModel,
    TargetVersionEventModel,
    TargetVersionModel,
    VirtualPortfolioEventModel,
    VirtualPortfolioModel,
)


def _error(code: app.TargetServiceErrorCode) -> app.TargetServiceError:
    return app.TargetServiceError(
        code,
        {
            app.TargetServiceErrorCode.NOT_FOUND: "The requested resource was not found.",
            app.TargetServiceErrorCode.IMMUTABLE_VERSION: "Published target content is immutable.",
            app.TargetServiceErrorCode.INVALID_STATE_TRANSITION: "Invalid lifecycle transition.",
            app.TargetServiceErrorCode.IDEMPOTENCY_KEY_REUSED: "Idempotency request mismatch.",
            app.TargetServiceErrorCode.TARGET_VALIDATION_FAILED: "Target validation failed.",
            app.TargetServiceErrorCode.CURRENCY_MISMATCH: "The target currency does not match.",
            app.TargetServiceErrorCode.VALIDATION_FAILED: "The target request is invalid.",
        }.get(code, "The target request cannot be completed."),
    )


class PostgresTargetService(app.TargetService):
    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        cursor_signing_key: bytes,
        clock: Callable[[], datetime] | None = None,
        cursor_ttl_seconds: int = 3600,
        max_active_collection_snapshots_per_owner: int = 64,
        max_active_collection_members_per_owner: int = 250_000,
    ) -> None:
        self._sessions = sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._authorizer = Authorizer()
        self._cursors = CursorCodec(
            cursor_signing_key, clock=self._clock, ttl_seconds=cursor_ttl_seconds
        )
        self._ttl = cursor_ttl_seconds
        self._snapshot_quota = max_active_collection_snapshots_per_owner
        self._member_quota = max_active_collection_members_per_owner

    def _now(self) -> datetime:
        return require_utc(self._clock())

    async def _run[T](
        self,
        principal: Principal,
        scope: Scope,
        operation: Callable[[Session, UUID], T],
    ) -> T:
        self._authorizer.require_scope(principal, scope, now=self._now())
        owner = UUID(principal.owner_id)

        def execute() -> T:
            try:
                with self._sessions() as session, session.begin():
                    # Serialize normalized projections and commands without changing the
                    # READ COMMITTED isolation required by the separate capacity lock.
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                        {"key": f"targets:{owner}"},
                    )
                    return operation(session, owner)
            except IntegrityError:
                rejection = app.TargetServiceErrorCode.VALIDATION_FAILED
            except SQLAlchemyError:
                rejection = app.TargetServiceErrorCode.TARGETS_UNAVAILABLE
            # Leave the exception handler after rollback, so database parameters and
            # statement details are absent from both cause and context of the public error.
            raise _error(rejection)

        return await asyncio.to_thread(execute)

    def _account(self, session: Session, principal: Principal, account_id: UUID | None) -> None:
        if account_id is None:
            return
        self._authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=self._now())
        owner = session.scalar(
            select(BrokerConnectionModel.owner_id)
            .join(BrokerAccountModel)
            .where(BrokerAccountModel.id == account_id)
        )
        if owner != UUID(principal.owner_id):
            raise _error(app.TargetServiceErrorCode.NOT_FOUND)

    def _portfolio(
        self, session: Session, principal: Principal, portfolio_id: str
    ) -> VirtualPortfolioModel:
        model = session.scalar(
            select(VirtualPortfolioModel).where(
                VirtualPortfolioModel.id == UUID(portfolio_id),
                VirtualPortfolioModel.owner_id == UUID(principal.owner_id),
            )
        )
        if model is None:
            raise _error(app.TargetServiceErrorCode.NOT_FOUND)
        self._account(session, principal, model.broker_account_id)
        return model

    def _version(
        self, session: Session, principal: Principal, version_id: str
    ) -> TargetVersionModel:
        model = session.scalar(
            select(TargetVersionModel).where(
                TargetVersionModel.id == UUID(version_id),
                TargetVersionModel.owner_id == UUID(principal.owner_id),
            )
        )
        if model is None:
            raise _error(app.TargetServiceErrorCode.NOT_FOUND)
        self._portfolio(session, principal, str(model.virtual_portfolio_id))
        return model

    def _replay(
        self,
        session: Session,
        owner: UUID,
        account: UUID | None,
        kind: str,
        key: str,
        payload: object,
    ) -> tuple[TargetCommandIdentityModel | None, str]:
        app.validate_target_idempotency_key(key)
        digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        row = session.scalar(
            select(TargetCommandIdentityModel).where(
                TargetCommandIdentityModel.owner_id == owner,
                TargetCommandIdentityModel.broker_account_id == account,
                TargetCommandIdentityModel.command_kind == kind,
                TargetCommandIdentityModel.idempotency_key == key,
            )
        )
        if row is not None and row.request_digest != digest:
            raise _error(app.TargetServiceErrorCode.IDEMPOTENCY_KEY_REUSED)
        return row, digest

    def _record(
        self,
        session: Session,
        principal: Principal,
        portfolio: VirtualPortfolioModel,
        kind: str,
        key: str,
        digest: str,
        *,
        version: TargetVersionModel | None = None,
        validation: TargetValidationResultModel | None = None,
    ) -> None:
        session.add(
            TargetCommandIdentityModel(
                owner_id=portfolio.owner_id,
                broker_account_id=portfolio.broker_account_id,
                command_kind=kind,
                idempotency_key=key,
                request_digest=digest,
                virtual_portfolio_id=portfolio.id,
                target_version_id=None if version is None else version.id,
                validation_id=None if validation is None else validation.id,
                actor_principal_id=principal.principal_id,
                created_at=self._now(),
            )
        )
        session.flush()

    def _portfolio_event(
        self,
        session: Session,
        model: VirtualPortfolioModel,
        kind: str,
        actor: str,
        correlation: str,
    ) -> None:
        sequence = session.scalar(
            select(func.coalesce(func.max(VirtualPortfolioEventModel.sequence), 0)).where(
                VirtualPortfolioEventModel.virtual_portfolio_id == model.id
            )
        )
        session.add(
            VirtualPortfolioEventModel(
                owner_id=model.owner_id,
                virtual_portfolio_id=model.id,
                sequence=int(sequence or 0) + 1,
                kind=kind,
                actor_principal_id=actor,
                correlation_id=correlation,
                created_at=self._now(),
            )
        )
        session.flush()

    def _event(
        self,
        session: Session,
        model: TargetVersionModel,
        kind: str,
        actor: str,
        correlation: str,
        validation_id: UUID | None = None,
    ) -> None:
        # Audit guards compare against the exact persisted aggregate revision.
        session.flush()
        previous = session.scalar(
            select(TargetVersionEventModel)
            .where(TargetVersionEventModel.target_version_id == model.id)
            .order_by(TargetVersionEventModel.sequence.desc())
            .limit(1)
        )
        session.add(
            TargetVersionEventModel(
                owner_id=model.owner_id,
                target_version_id=model.id,
                sequence=1 if previous is None else previous.sequence + 1,
                previous_event_id=None if previous is None else previous.id,
                kind=kind,
                actor_principal_id=actor,
                correlation_id=correlation,
                validation_id=validation_id,
                effective_at=model.effective_at,
                created_at=self._now(),
            )
        )
        session.flush()

    def _portfolio_view(
        self, session: Session, model: VirtualPortfolioModel
    ) -> app.VirtualPortfolioView:
        active = session.scalar(
            select(TargetVersionModel.id).where(
                TargetVersionModel.virtual_portfolio_id == model.id,
                TargetVersionModel.state == "active",
            )
        )
        published = session.scalar(
            select(TargetVersionModel.id)
            .where(
                TargetVersionModel.virtual_portfolio_id == model.id,
                TargetVersionModel.published_at.is_not(None),
            )
            .limit(1)
        )
        state = (
            app.VirtualPortfolioState.ARCHIVED
            if model.archived
            else (
                app.VirtualPortfolioState.ACTIVE
                if published is not None
                else app.VirtualPortfolioState.DRAFT
            )
        )
        return app.VirtualPortfolioView(
            str(model.id),
            None if model.broker_account_id is None else str(model.broker_account_id),
            model.name,
            model.description,
            model.reporting_currency,
            model.revision,
            state,
            model.created_at,
            model.updated_at,
            None if active is None or model.archived else str(active),
        )

    def _catalog(self, session: Session, content: domain.TargetContent) -> domain.TargetCatalog:
        instrument_ids = {
            n.holding.instrument_id
            for n in content.nodes
            if n.holding is not None and n.holding.instrument_id is not None
        }
        listing_ids = {
            identifier
            for n in content.nodes
            if n.holding is not None
            for identifier in (n.holding.listing_id, n.holding.preferred_listing_id)
            if identifier is not None
        }
        instrument_ids.update(
            e.instrument_id for e in content.exclusions if e.instrument_id is not None
        )
        listing_ids.update(e.listing_id for e in content.exclusions if e.listing_id is not None)
        listings = tuple(
            session.scalars(select(ListingModel).where(ListingModel.id.in_(listing_ids)))
        )
        if len(listings) != len(listing_ids):
            raise _error(app.TargetServiceErrorCode.NOT_FOUND)
        instrument_ids.update(listing.instrument_id for listing in listings)
        instruments = tuple(
            session.scalars(select(InstrumentModel).where(InstrumentModel.id.in_(instrument_ids)))
        )
        if len(instruments) != len(instrument_ids):
            raise _error(app.TargetServiceErrorCode.NOT_FOUND)
        return domain.TargetCatalog(
            tuple(domain.TargetInstrumentReference(i.id) for i in instruments),
            tuple(
                domain.TargetListingReference(
                    listing.id, listing.instrument_id, listing.status == "active"
                )
                for listing in listings
            ),
        )

    def _content(self, session: Session, version: TargetVersionModel) -> domain.TargetContent:
        nodes = tuple(
            session.scalars(
                select(TargetNodeModel)
                .where(TargetNodeModel.target_version_id == version.id)
                .order_by(TargetNodeModel.key)
            )
        )
        keys = {node.id: node.key for node in nodes}
        holdings = {
            h.node_id: h
            for h in session.scalars(
                select(TargetHoldingModel).where(TargetHoldingModel.target_version_id == version.id)
            )
        }
        decisions = {
            m.holding_id: m
            for m in session.scalars(
                select(TargetMappingDecisionModel).where(
                    TargetMappingDecisionModel.target_version_id == version.id
                )
            )
        }
        values: list[domain.TargetNode] = []
        for node in nodes:
            holding = holdings.get(node.id)
            mapping = None
            if holding is not None:
                decision = decisions[holding.id]
                identifier = (
                    None
                    if decision.identifier_kind is None
                    else domain.TargetIdentifier(
                        domain.TargetIdentifierKind(decision.identifier_kind),
                        decision.identifier_value or "",
                        decision.identifier_provider,
                    )
                )
                mapping = domain.TargetHoldingMapping(
                    domain.TargetMappingState(holding.mapping_state),
                    holding.instrument_id,
                    holding.listing_id,
                    holding.preferred_listing_id,
                    identifier,
                    holding.reason,
                )
            values.append(
                domain.TargetNode(
                    node.key,
                    None if node.parent_id is None else keys[node.parent_id],
                    domain.TargetNodeKind(node.kind),
                    node.name,
                    node.sibling_order,
                    node.weight,
                    mapping,
                )
            )
        constraints = tuple(
            domain.TargetConstraint(
                c.key,
                domain.TargetConstraintKind(c.kind),
                None if c.node_id is None else keys[c.node_id],
                c.amount,
                None if c.currency is None else CurrencyCode(c.currency),
                c.weight,
                c.enabled,
                c.line_count,
                c.coefficient,
            )
            for c in session.scalars(
                select(TargetConstraintModel)
                .where(TargetConstraintModel.target_version_id == version.id)
                .order_by(TargetConstraintModel.key)
            )
        )
        exclusions = tuple(
            domain.TargetExclusion(
                e.key,
                None if e.node_id is None else keys[e.node_id],
                e.instrument_id,
                e.listing_id,
                e.reason,
            )
            for e in session.scalars(
                select(TargetExclusionModel)
                .where(TargetExclusionModel.target_version_id == version.id)
                .order_by(TargetExclusionModel.key)
            )
        )
        return domain.TargetContent(tuple(values), constraints, exclusions)

    def _store_content(
        self,
        session: Session,
        version: TargetVersionModel,
        content: domain.TargetContent,
        actor: str,
    ) -> None:
        self._catalog(session, content)
        keys = {node.key: uuid4() for node in content.nodes}
        if len(keys) != len(content.nodes) or any(
            n.parent_key is not None and n.parent_key not in keys for n in content.nodes
        ):
            raise _error(app.TargetServiceErrorCode.VALIDATION_FAILED)
        references = [c.node_key for c in content.constraints if c.node_key is not None]
        references.extend(e.node_key for e in content.exclusions if e.node_key is not None)
        if (
            any(key not in keys for key in references)
            or len({c.key for c in content.constraints}) != len(content.constraints)
            or len({e.key for e in content.exclusions}) != len(content.exclusions)
        ):
            raise _error(app.TargetServiceErrorCode.VALIDATION_FAILED)
        for model in (
            TargetMappingDecisionModel,
            TargetHoldingModel,
            TargetConstraintModel,
            TargetExclusionModel,
            TargetNodeModel,
        ):
            session.execute(delete(model).where(model.target_version_id == version.id))
        for node in content.nodes:
            session.add(
                TargetNodeModel(
                    id=keys[node.key],
                    owner_id=version.owner_id,
                    target_version_id=version.id,
                    key=node.key,
                    parent_id=None if node.parent_key is None else keys[node.parent_key],
                    kind=node.kind.value,
                    name=node.name,
                    sibling_order=node.order,
                    weight=node.weight,
                    created_at=self._now(),
                )
            )
        session.flush()
        for node in content.nodes:
            if node.holding is None:
                continue
            mapping = node.holding
            holding = TargetHoldingModel(
                owner_id=version.owner_id,
                target_version_id=version.id,
                node_id=keys[node.key],
                instrument_id=mapping.instrument_id,
                listing_id=mapping.listing_id,
                preferred_listing_id=mapping.preferred_listing_id,
                mapping_state=mapping.state.value,
                reason=mapping.reason,
                created_at=self._now(),
            )
            session.add(holding)
            session.flush()
            identifier = mapping.requested_identifier
            session.add(
                TargetMappingDecisionModel(
                    owner_id=version.owner_id,
                    target_version_id=version.id,
                    holding_id=holding.id,
                    identifier_kind=None if identifier is None else identifier.kind.value,
                    identifier_value=None if identifier is None else identifier.value,
                    identifier_provider=None if identifier is None else identifier.provider,
                    method_version=domain.TARGET_VALIDATION_VERSION,
                    actor_principal_id=actor,
                    confidence=None,
                    source_kind="owner",
                    effective_at=version.effective_at,
                    created_at=self._now(),
                )
            )
        for constraint in content.constraints:
            session.add(
                TargetConstraintModel(
                    owner_id=version.owner_id,
                    target_version_id=version.id,
                    key=constraint.key,
                    node_id=None if constraint.node_key is None else keys[constraint.node_key],
                    kind=constraint.kind.value,
                    amount=constraint.amount,
                    currency=None if constraint.currency is None else constraint.currency.value,
                    weight=constraint.weight,
                    enabled=constraint.enabled,
                    line_count=constraint.count,
                    coefficient=constraint.coefficient,
                    created_at=self._now(),
                )
            )
        for exclusion in content.exclusions:
            session.add(
                TargetExclusionModel(
                    owner_id=version.owner_id,
                    target_version_id=version.id,
                    key=exclusion.key,
                    node_id=None if exclusion.node_key is None else keys[exclusion.node_key],
                    instrument_id=exclusion.instrument_id,
                    listing_id=exclusion.listing_id,
                    reason=exclusion.reason,
                    created_at=self._now(),
                )
            )
        session.flush()

    def _validation_view(
        self, session: Session, row: TargetValidationResultModel
    ) -> app.TargetValidationView:
        issues = tuple(
            domain.TargetValidationIssue(
                i.code,
                domain.TargetIssueSeverity(i.severity),
                i.message,
                tuple(i.node_keys),
                tuple(i.constraint_keys),
            )
            for i in session.scalars(
                select(TargetValidationIssueModel)
                .where(TargetValidationIssueModel.validation_id == row.id)
                .order_by(TargetValidationIssueModel.ordinal)
            )
        )
        adjustments = tuple(
            domain.TargetNormalizationAdjustment(
                a.node_key,
                a.parent_key,
                a.original_weight,
                a.normalized_weight,
                a.original_sum,
                a.remainder_rank,
            )
            for a in session.scalars(
                select(TargetNormalizationAdjustmentModel)
                .where(TargetNormalizationAdjustmentModel.validation_id == row.id)
                .order_by(TargetNormalizationAdjustmentModel.node_key)
            )
        )
        return app.TargetValidationView(
            str(row.id),
            str(row.target_version_id),
            row.input_revision,
            row.result_revision,
            row.input_digest,
            row.result_digest,
            row.valid,
            row.normalization_requested,
            row.normalization_applied,
            issues,
            adjustments,
            row.created_at,
        )

    def _version_view(self, session: Session, row: TargetVersionModel) -> app.TargetVersionView:
        content = self._content(session, row)
        projection = domain.flatten_target_content(content)
        latest = session.scalar(
            select(TargetValidationResultModel)
            .where(TargetValidationResultModel.target_version_id == row.id)
            .order_by(
                TargetValidationResultModel.result_revision.desc(),
                TargetValidationResultModel.created_at.desc(),
                TargetValidationResultModel.id.desc(),
            )
            .limit(1)
        )
        return app.TargetVersionView(
            str(row.id),
            str(row.virtual_portfolio_id),
            row.version_number,
            row.revision,
            row.reporting_currency,
            row.effective_at,
            app.TargetVersionState(row.state),
            content,
            row.created_at,
            row.updated_at,
            row.published_at,
            row.content_digest,
            None if row.source_version_id is None else str(row.source_version_id),
            None if latest is None else self._validation_view(session, latest),
            () if projection is None else projection[0],
            None if projection is None else projection[1],
        )

    def _editable(
        self, portfolio: VirtualPortfolioModel, version: TargetVersionModel | None = None
    ) -> None:
        if portfolio.archived:
            raise _error(app.TargetServiceErrorCode.INVALID_STATE_TRANSITION)
        if version is not None:
            if version.published_at is not None:
                raise _error(app.TargetServiceErrorCode.IMMUTABLE_VERSION)
            if version.state != "draft":
                raise _error(app.TargetServiceErrorCode.INVALID_STATE_TRANSITION)

    async def create_virtual_portfolio(
        self,
        principal: Principal,
        command: app.CreateVirtualPortfolioCommand,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.VirtualPortfolioView:
        def execute(session: Session, owner: UUID) -> app.VirtualPortfolioView:
            account = None if command.account_id is None else UUID(command.account_id)
            self._account(session, principal, account)
            previous, digest = self._replay(
                session, owner, account, "create_portfolio", idempotency_key, command
            )
            if previous is not None:
                return self._portfolio_view(
                    session, self._portfolio(session, principal, str(previous.virtual_portfolio_id))
                )
            row = VirtualPortfolioModel(
                owner_id=owner,
                broker_account_id=account,
                name=command.name,
                description=command.description,
                reporting_currency=command.reporting_currency.value,
                revision=1,
                archived=False,
                updated_at=self._now(),
                created_at=self._now(),
                actor_principal_id=principal.principal_id,
            )
            session.add(row)
            session.flush()
            self._portfolio_event(session, row, "created", principal.principal_id, correlation_id)
            self._record(session, principal, row, "create_portfolio", idempotency_key, digest)
            return self._portfolio_view(session, row)

        return await self._run(principal, Scope.TARGETS_WRITE, execute)

    async def get_virtual_portfolio(
        self, principal: Principal, portfolio_id: str
    ) -> app.VirtualPortfolioView:
        return await self._run(
            principal,
            Scope.TARGETS_READ,
            lambda s, _: self._portfolio_view(s, self._portfolio(s, principal, portfolio_id)),
        )

    async def update_virtual_portfolio(
        self,
        principal: Principal,
        portfolio_id: str,
        command: app.UpdateVirtualPortfolioCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.VirtualPortfolioView:
        def execute(session: Session, owner: UUID) -> app.VirtualPortfolioView:
            row = self._portfolio(session, principal, portfolio_id)
            previous, digest = self._replay(
                session,
                owner,
                row.broker_account_id,
                "update_portfolio",
                idempotency_key,
                (portfolio_id, command),
            )
            if previous is not None:
                return self._portfolio_view(session, row)
            app.require_target_revision(if_match, portfolio_id, row.revision)
            self._editable(row)
            if command.name is not None:
                row.name = command.name
            if command.description is not None:
                row.description = command.description
            row.revision += 1
            row.updated_at = self._now()
            self._portfolio_event(
                session, row, "metadata_updated", principal.principal_id, correlation_id
            )
            self._record(session, principal, row, "update_portfolio", idempotency_key, digest)
            return self._portfolio_view(session, row)

        return await self._run(principal, Scope.TARGETS_WRITE, execute)

    async def archive_virtual_portfolio(
        self,
        principal: Principal,
        portfolio_id: str,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.VirtualPortfolioView:
        def execute(session: Session, owner: UUID) -> app.VirtualPortfolioView:
            row = self._portfolio(session, principal, portfolio_id)
            previous, digest = self._replay(
                session,
                owner,
                row.broker_account_id,
                "archive_portfolio",
                idempotency_key,
                portfolio_id,
            )
            if previous is not None:
                return self._portfolio_view(session, row)
            app.require_target_revision(if_match, portfolio_id, row.revision)
            self._editable(row)
            row.archived = True
            row.revision += 1
            row.updated_at = self._now()
            for version in session.scalars(
                select(TargetVersionModel).where(
                    TargetVersionModel.virtual_portfolio_id == row.id,
                    TargetVersionModel.state == "active",
                )
            ):
                version.state = "archived"
                version.revision += 1
                version.updated_at = self._now()
                self._event(session, version, "archived", principal.principal_id, correlation_id)
            self._portfolio_event(session, row, "archived", principal.principal_id, correlation_id)
            self._record(session, principal, row, "archive_portfolio", idempotency_key, digest)
            return self._portfolio_view(session, row)

        return await self._run(principal, Scope.TARGETS_WRITE, execute)

    async def create_target_version(
        self,
        principal: Principal,
        portfolio_id: str,
        command: app.CreateTargetVersionCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.TargetVersionView:
        def execute(session: Session, owner: UUID) -> app.TargetVersionView:
            portfolio = self._portfolio(session, principal, portfolio_id)
            content = command.content
            source = None
            if command.source_version_id is not None:
                self._authorizer.require_scope(principal, Scope.TARGETS_READ, now=self._now())
                source = self._version(session, principal, command.source_version_id)
                if source.reporting_currency != portfolio.reporting_currency:
                    raise _error(app.TargetServiceErrorCode.CURRENCY_MISMATCH)
                content = self._content(session, source)
            previous, digest = self._replay(
                session,
                owner,
                portfolio.broker_account_id,
                "create_version",
                idempotency_key,
                (portfolio_id, command),
            )
            if previous is not None:
                return self._version_view(
                    session, self._version(session, principal, str(previous.target_version_id))
                )
            app.require_target_revision(if_match, portfolio_id, portfolio.revision)
            self._editable(portfolio)
            assert content is not None
            number = session.scalar(
                select(func.coalesce(func.max(TargetVersionModel.version_number), 0)).where(
                    TargetVersionModel.virtual_portfolio_id == portfolio.id
                )
            )
            version = TargetVersionModel(
                owner_id=owner,
                virtual_portfolio_id=portfolio.id,
                source_version_id=None if source is None else source.id,
                parent_version_id=(
                    source.id
                    if source is not None and source.virtual_portfolio_id == portfolio.id
                    else None
                ),
                version_number=int(number or 0) + 1,
                revision=1,
                reporting_currency=portfolio.reporting_currency,
                effective_at=command.effective_at,
                published_at=None,
                state="draft",
                content_digest=None,
                updated_at=self._now(),
                created_at=self._now(),
                actor_principal_id=principal.principal_id,
            )
            session.add(version)
            session.flush()
            self._store_content(session, version, content, principal.principal_id)
            portfolio.revision += 1
            portfolio.updated_at = self._now()
            self._event(session, version, "draft_created", principal.principal_id, correlation_id)
            self._record(
                session,
                principal,
                portfolio,
                "create_version",
                idempotency_key,
                digest,
                version=version,
            )
            return self._version_view(session, version)

        return await self._run(principal, Scope.TARGETS_WRITE, execute)

    async def get_target_version(
        self, principal: Principal, version_id: str
    ) -> app.TargetVersionView:
        return await self._run(
            principal,
            Scope.TARGETS_READ,
            lambda s, _: self._version_view(s, self._version(s, principal, version_id)),
        )

    async def replace_target_draft(
        self,
        principal: Principal,
        version_id: str,
        command: app.ReplaceTargetDraftCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.TargetVersionView:
        def execute(session: Session, owner: UUID) -> app.TargetVersionView:
            version = self._version(session, principal, version_id)
            portfolio = self._portfolio(session, principal, str(version.virtual_portfolio_id))
            previous, digest = self._replay(
                session,
                owner,
                portfolio.broker_account_id,
                "replace_draft",
                idempotency_key,
                (version_id, command),
            )
            if previous is not None:
                return self._version_view(session, version)
            app.require_target_revision(if_match, version_id, version.revision)
            self._editable(portfolio, version)
            self._store_content(session, version, command.content, principal.principal_id)
            version.effective_at = command.effective_at
            version.revision += 1
            version.updated_at = self._now()
            self._event(session, version, "draft_updated", principal.principal_id, correlation_id)
            self._record(
                session,
                principal,
                portfolio,
                "replace_draft",
                idempotency_key,
                digest,
                version=version,
            )
            return self._version_view(session, version)

        return await self._run(principal, Scope.TARGETS_WRITE, execute)

    async def validate_target_version(
        self,
        principal: Principal,
        version_id: str,
        command: app.ValidateTargetCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.TargetValidationView:
        def execute(session: Session, owner: UUID) -> app.TargetValidationView:
            version = self._version(session, principal, version_id)
            portfolio = self._portfolio(session, principal, str(version.virtual_portfolio_id))
            previous, digest = self._replay(
                session,
                owner,
                portfolio.broker_account_id,
                "validate_version",
                idempotency_key,
                (version_id, command),
            )
            if previous is not None:
                saved = session.get(TargetValidationResultModel, previous.validation_id)
                assert saved is not None
                return self._validation_view(session, saved)
            app.require_target_revision(if_match, version_id, version.revision)
            self._editable(portfolio, version)
            content = self._content(session, version)
            result = domain.validate_target_content(
                content,
                reporting_currency=CurrencyCode(version.reporting_currency),
                effective_at=version.effective_at,
                catalog=self._catalog(session, content),
                normalize=command.normalize,
            )
            initial_revision = version.revision
            changed = result.input_digest != result.result_digest
            if changed:
                self._store_content(session, version, result.content, principal.principal_id)
            # Validation is visible metadata even when the economic content is unchanged.
            version.revision += 1
            version.updated_at = self._now()
            row = TargetValidationResultModel(
                owner_id=owner,
                target_version_id=version.id,
                input_revision=initial_revision,
                result_revision=version.revision,
                input_digest=result.input_digest,
                result_digest=result.result_digest,
                method_version=domain.TARGET_VALIDATION_VERSION,
                normalization_requested=command.normalize,
                normalization_applied=changed,
                valid=result.valid,
                effective_weight_rounding_residual=result.effective_weight_rounding_residual,
                actor_principal_id=principal.principal_id,
                created_at=self._now(),
            )
            session.add(row)
            session.flush()
            for ordinal, issue in enumerate(result.issues):
                session.add(
                    TargetValidationIssueModel(
                        owner_id=owner,
                        validation_id=row.id,
                        ordinal=ordinal,
                        code=issue.code,
                        severity=issue.severity.value,
                        node_keys=list(issue.node_keys),
                        constraint_keys=list(issue.constraint_keys),
                        message=issue.message,
                        created_at=self._now(),
                    )
                )
            for adjustment in result.adjustments:
                session.add(
                    TargetNormalizationAdjustmentModel(
                        owner_id=owner,
                        validation_id=row.id,
                        node_key=adjustment.node_key,
                        parent_key=adjustment.parent_key,
                        original_weight=adjustment.original_weight,
                        normalized_weight=adjustment.normalized_weight,
                        original_sum=adjustment.original_sibling_sum,
                        remainder_rank=adjustment.remainder_rank,
                        created_at=self._now(),
                    )
                )
            if changed:
                self._event(
                    session,
                    version,
                    "draft_updated",
                    principal.principal_id,
                    correlation_id,
                    row.id,
                )
            self._event(
                session, version, "validated", principal.principal_id, correlation_id, row.id
            )
            self._record(
                session,
                principal,
                portfolio,
                "validate_version",
                idempotency_key,
                digest,
                version=version,
                validation=row,
            )
            return self._validation_view(session, row)

        return await self._run(principal, Scope.TARGETS_WRITE, execute)

    def _activate(
        self,
        session: Session,
        portfolio: VirtualPortfolioModel,
        version: TargetVersionModel,
        actor: str,
        correlation: str,
    ) -> None:
        for previous in session.scalars(
            select(TargetVersionModel).where(
                TargetVersionModel.virtual_portfolio_id == portfolio.id,
                TargetVersionModel.state == "active",
                TargetVersionModel.id != version.id,
            )
        ):
            previous.state = "superseded"
            previous.revision += 1
            previous.updated_at = self._now()
            self._event(session, previous, "superseded", actor, correlation)
        session.flush()
        version.state = "active"
        version.revision += 1
        version.updated_at = self._now()
        portfolio.revision += 1
        portfolio.updated_at = self._now()
        self._event(session, version, "activated", actor, correlation)

    async def publish_target_version(
        self,
        principal: Principal,
        version_id: str,
        command: app.PublishTargetCommand,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.TargetVersionView:
        def execute(session: Session, owner: UUID) -> app.TargetVersionView:
            version = self._version(session, principal, version_id)
            portfolio = self._portfolio(session, principal, str(version.virtual_portfolio_id))
            previous, digest = self._replay(
                session,
                owner,
                portfolio.broker_account_id,
                "publish_version",
                idempotency_key,
                (version_id, command),
            )
            if previous is not None:
                return self._version_view(session, version)
            app.require_target_revision(if_match, version_id, version.revision)
            self._editable(portfolio, version)
            validation = session.scalar(
                select(TargetValidationResultModel).where(
                    TargetValidationResultModel.id == UUID(command.validation_id),
                    TargetValidationResultModel.owner_id == owner,
                    TargetValidationResultModel.target_version_id == version.id,
                )
            )
            if validation is None:
                raise _error(app.TargetServiceErrorCode.NOT_FOUND)
            content = self._content(session, version)
            current = domain.validate_target_content(
                content,
                reporting_currency=CurrencyCode(version.reporting_currency),
                effective_at=version.effective_at,
                catalog=self._catalog(session, content),
            )
            current_digest = current.result_digest
            if (
                not validation.valid
                or not current.valid
                or validation.result_revision != version.revision
                or validation.result_digest != current_digest
            ):
                raise _error(app.TargetServiceErrorCode.TARGET_VALIDATION_FAILED)
            version.content_digest = current_digest
            version.published_at = self._now()
            version.updated_at = self._now()
            version.revision += 1
            version.state = "scheduled"
            self._event(
                session, version, "published", principal.principal_id, correlation_id, validation.id
            )
            if version.effective_at <= self._now():
                self._activate(session, portfolio, version, principal.principal_id, correlation_id)
            self._record(
                session,
                principal,
                portfolio,
                "publish_version",
                idempotency_key,
                digest,
                version=version,
            )
            return self._version_view(session, version)

        return await self._run(principal, Scope.TARGETS_WRITE, execute)

    async def archive_target_version(
        self,
        principal: Principal,
        version_id: str,
        *,
        if_match: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> app.TargetVersionView:
        def execute(session: Session, owner: UUID) -> app.TargetVersionView:
            version = self._version(session, principal, version_id)
            portfolio = self._portfolio(session, principal, str(version.virtual_portfolio_id))
            previous, digest = self._replay(
                session,
                owner,
                portfolio.broker_account_id,
                "archive_version",
                idempotency_key,
                version_id,
            )
            if previous is not None:
                return self._version_view(session, version)
            app.require_target_revision(if_match, version_id, version.revision)
            if version.state == "archived":
                raise _error(app.TargetServiceErrorCode.INVALID_STATE_TRANSITION)
            version.state = "archived"
            version.revision += 1
            version.updated_at = self._now()
            portfolio.revision += 1
            portfolio.updated_at = self._now()
            self._event(session, version, "archived", principal.principal_id, correlation_id)
            self._record(
                session,
                principal,
                portfolio,
                "archive_version",
                idempotency_key,
                digest,
                version=version,
            )
            return self._version_view(session, version)

        return await self._run(principal, Scope.TARGETS_WRITE, execute)

    async def activate_due_versions(self, *, limit: int = 100) -> int:
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("activation limit must be 1..1000")

        def execute() -> int:
            with self._sessions() as session:
                candidates = tuple(
                    session.execute(
                        select(TargetVersionModel.id, TargetVersionModel.owner_id)
                        .join(
                            VirtualPortfolioModel,
                            TargetVersionModel.virtual_portfolio_id == VirtualPortfolioModel.id,
                        )
                        .where(
                            TargetVersionModel.state == "scheduled",
                            TargetVersionModel.effective_at <= self._now(),
                            VirtualPortfolioModel.archived.is_(False),
                        )
                        .order_by(
                            TargetVersionModel.effective_at,
                            TargetVersionModel.version_number,
                            TargetVersionModel.id,
                        )
                        .limit(limit)
                    )
                )
            activated = 0
            for identifier, owner in candidates:
                with self._sessions() as session, session.begin():
                    locked = session.scalar(
                        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key,0))"),
                        {"key": f"targets:{owner}"},
                    )
                    if not locked:
                        continue
                    version = session.get(TargetVersionModel, identifier)
                    assert version is not None
                    portfolio = session.get(VirtualPortfolioModel, version.virtual_portfolio_id)
                    assert portfolio is not None
                    if (
                        not portfolio.archived
                        and version.state == "scheduled"
                        and version.effective_at <= self._now()
                    ):
                        active = session.scalar(
                            select(TargetVersionModel).where(
                                TargetVersionModel.virtual_portfolio_id == portfolio.id,
                                TargetVersionModel.state == "active",
                            )
                        )
                        if (
                            active is not None
                            and active.published_at is not None
                            and version.published_at is not None
                            and active.published_at >= version.effective_at
                            and active.published_at > version.published_at
                        ):
                            # A later explicit publication overtook this overdue intent.
                            # Preserve the missed schedule in audit without replacing the
                            # owner's newer selection when the dispatcher resumes.
                            version.state = "superseded"
                            version.revision += 1
                            version.updated_at = self._now()
                            self._event(
                                session,
                                version,
                                "superseded",
                                "system:target-scheduler",
                                "target-scheduled-supersession",
                            )
                            continue
                        self._activate(
                            session,
                            portfolio,
                            version,
                            "system:target-scheduler",
                            "target-scheduled-activation",
                        )
                        activated += 1
            return activated

        return await asyncio.to_thread(execute)

    def _store(self, session: Session) -> CollectionSnapshotStore:
        return CollectionSnapshotStore(
            session,
            self._cursors,
            ttl_seconds=self._ttl,
            max_active_snapshots_per_owner=self._snapshot_quota,
            max_active_members_per_owner=self._member_quota,
        )

    async def list_virtual_portfolios(
        self, principal: Principal, *, query: app.VirtualPortfolioQuery
    ) -> Page[app.VirtualPortfolioView]:
        def execute(session: Session, owner: UUID) -> Page[app.VirtualPortfolioView]:
            account = None if query.account_id is None else UUID(query.account_id)
            self._account(session, principal, account)
            resource = (
                CollectionSnapshotResource.PORTFOLIOS_NAME
                if query.sort is app.VirtualPortfolioSort.NAME_ASC
                else CollectionSnapshotResource.PORTFOLIOS_UPDATED
            )
            definition = CollectionSnapshotDefinition(
                resource,
                owner,
                account,
                collection_filter_fingerprint(query.state, query.search, query.sort),
            )
            store = self._store(session)
            if query.cursor is None:
                statement = select(VirtualPortfolioModel.id).where(
                    VirtualPortfolioModel.owner_id == owner,
                    VirtualPortfolioModel.broker_account_id == account,
                )
                published = (
                    select(TargetVersionModel.id)
                    .where(
                        TargetVersionModel.virtual_portfolio_id == VirtualPortfolioModel.id,
                        TargetVersionModel.published_at.is_not(None),
                    )
                    .exists()
                )
                if query.state is app.VirtualPortfolioStateFilter.ARCHIVED:
                    statement = statement.where(VirtualPortfolioModel.archived.is_(True))
                elif query.state is not app.VirtualPortfolioStateFilter.ALL:
                    statement = statement.where(
                        VirtualPortfolioModel.archived.is_(False),
                        published
                        if query.state is app.VirtualPortfolioStateFilter.ACTIVE
                        else ~published,
                    )
                if query.search:
                    statement = statement.where(
                        func.lower(VirtualPortfolioModel.name).contains(
                            query.search, autoescape=True
                        )
                    )
                statement = (
                    statement.order_by(
                        func.lower(VirtualPortfolioModel.name), VirtualPortfolioModel.id
                    )
                    if query.sort is app.VirtualPortfolioSort.NAME_ASC
                    else statement.order_by(
                        VirtualPortfolioModel.updated_at.desc(), VirtualPortfolioModel.id.desc()
                    )
                )
                page = store.materialize(
                    definition,
                    lambda: session.scalars(statement.execution_options(yield_per=1000)),
                    limit=query.limit,
                )
                # Persist each member's active immutable target reference in the same transaction.
                from sqlalchemy import insert

                selected = (
                    select(
                        func.gen_random_uuid(),
                        CollectionQuerySnapshotMemberModel.snapshot_id,
                        VirtualPortfolioModel.owner_id,
                        VirtualPortfolioModel.id,
                        TargetVersionModel.id,
                        func.now(),
                    )
                    .select_from(CollectionQuerySnapshotMemberModel)
                    .join(
                        VirtualPortfolioModel,
                        VirtualPortfolioModel.id == CollectionQuerySnapshotMemberModel.record_id,
                    )
                    .outerjoin(
                        TargetVersionModel,
                        (TargetVersionModel.virtual_portfolio_id == VirtualPortfolioModel.id)
                        & (TargetVersionModel.state == "active")
                        & VirtualPortfolioModel.archived.is_(False),
                    )
                    .where(CollectionQuerySnapshotMemberModel.snapshot_id == page.snapshot_id)
                )
                session.execute(
                    insert(TargetCollectionReferenceModel).from_select(
                        [
                            "id",
                            "snapshot_id",
                            "owner_id",
                            "virtual_portfolio_id",
                            "target_version_id",
                            "created_at",
                        ],
                        selected,
                    )
                )
            else:
                page = store.resume(definition, cursor=query.cursor, limit=query.limit)
            references = {
                r.virtual_portfolio_id: r.target_version_id
                for r in session.scalars(
                    select(TargetCollectionReferenceModel).where(
                        TargetCollectionReferenceModel.snapshot_id == page.snapshot_id,
                        TargetCollectionReferenceModel.virtual_portfolio_id.in_(page.record_ids),
                    )
                )
            }
            rows = {
                r.id: r
                for r in session.scalars(
                    select(VirtualPortfolioModel).where(
                        VirtualPortfolioModel.id.in_(page.record_ids),
                        VirtualPortfolioModel.owner_id == owner,
                    )
                )
            }
            items = tuple(
                replace(
                    self._portfolio_view(session, rows[identifier]),
                    active_version_id=None
                    if references[identifier] is None
                    else str(references[identifier]),
                )
                for identifier in page.record_ids
            )
            return Page(items, page.next_cursor, page.limit, page.exact_total)

        return await self._run(principal, Scope.TARGETS_READ, execute)

    async def list_target_versions(
        self, principal: Principal, portfolio_id: str, *, query: app.TargetVersionQuery
    ) -> Page[app.TargetVersionView]:
        def execute(session: Session, owner: UUID) -> Page[app.TargetVersionView]:
            portfolio = self._portfolio(session, principal, portfolio_id)
            definition = CollectionSnapshotDefinition(
                CollectionSnapshotResource.TARGET_VERSIONS,
                owner,
                portfolio.broker_account_id,
                collection_filter_fingerprint(portfolio_id, query.state),
            )
            store = self._store(session)
            if query.cursor is None:
                statement = select(TargetVersionModel.id).where(
                    TargetVersionModel.virtual_portfolio_id == portfolio.id
                )
                if query.state is not app.TargetVersionStateFilter.ALL:
                    statement = statement.where(TargetVersionModel.state == query.state.value)
                page = store.materialize(
                    definition,
                    lambda: session.scalars(
                        statement.order_by(
                            TargetVersionModel.version_number.desc(), TargetVersionModel.id.desc()
                        ).execution_options(yield_per=1000)
                    ),
                    limit=query.limit,
                )
            else:
                page = store.resume(definition, cursor=query.cursor, limit=query.limit)
            return Page(
                tuple(
                    self._version_view(session, self._version(session, principal, str(identifier)))
                    for identifier in page.record_ids
                ),
                page.next_cursor,
                page.limit,
                page.exact_total,
            )

        return await self._run(principal, Scope.TARGETS_READ, execute)

    async def list_target_version_events(
        self, principal: Principal, version_id: str, *, query: app.TargetPageQuery
    ) -> Page[app.TargetVersionEventView]:
        def execute(session: Session, owner: UUID) -> Page[app.TargetVersionEventView]:
            version = self._version(session, principal, version_id)
            portfolio = self._portfolio(session, principal, str(version.virtual_portfolio_id))
            definition = CollectionSnapshotDefinition(
                CollectionSnapshotResource.TARGET_EVENTS,
                owner,
                portfolio.broker_account_id,
                collection_filter_fingerprint(version_id),
            )
            store = self._store(session)
            if query.cursor is None:
                statement = (
                    select(TargetVersionEventModel.id)
                    .where(TargetVersionEventModel.target_version_id == version.id)
                    .order_by(
                        TargetVersionEventModel.created_at.desc(), TargetVersionEventModel.id.desc()
                    )
                )
                page = store.materialize(
                    definition,
                    lambda: session.scalars(statement.execution_options(yield_per=1000)),
                    limit=query.limit,
                )
            else:
                page = store.resume(definition, cursor=query.cursor, limit=query.limit)
            rows = {
                r.id: r
                for r in session.scalars(
                    select(TargetVersionEventModel).where(
                        TargetVersionEventModel.id.in_(page.record_ids),
                        TargetVersionEventModel.owner_id == owner,
                    )
                )
            }
            items = tuple(
                app.TargetVersionEventView(
                    str(rows[i].id),
                    str(rows[i].target_version_id),
                    rows[i].sequence,
                    rows[i].kind,
                    rows[i].actor_principal_id,
                    rows[i].created_at,
                    rows[i].effective_at,
                    None if rows[i].validation_id is None else str(rows[i].validation_id),
                )
                for i in page.record_ids
            )
            return Page(items, page.next_cursor, page.limit, page.exact_total)

        return await self._run(principal, Scope.TARGETS_READ, execute)

    def _target_nodes_page(
        self,
        session: Session,
        version: TargetVersionModel,
        portfolio: VirtualPortfolioModel,
        *,
        parent_node_id: str | None,
        query: app.TargetPageQuery,
    ) -> Page[app.TargetHierarchyNodeView]:
        nodes = tuple(
            session.scalars(
                select(TargetNodeModel).where(TargetNodeModel.target_version_id == version.id)
            )
        )
        parent = (
            None
            if parent_node_id is None
            else next((n for n in nodes if str(n.id) == parent_node_id), None)
        )
        if parent_node_id is not None and parent is None:
            raise _error(app.TargetServiceErrorCode.NOT_FOUND)
        content = self._content(session, version)
        values_by_key = {node.key: node for node in content.nodes}
        children: dict[UUID | None, list[TargetNodeModel]] = {}
        for node in nodes:
            children.setdefault(node.parent_id, []).append(node)
        for siblings in children.values():
            siblings.sort(key=lambda node: (node.sibling_order, node.key))
        ordered: list[TargetNodeModel] = []
        visited: set[UUID] = set()
        if parent is not None:
            visited.add(parent.id)

        def visit(node: TargetNodeModel) -> None:
            if node.id in visited:
                return
            visited.add(node.id)
            ordered.append(node)
            for child in children.get(node.id, []):
                visit(child)

        for node in children.get(None if parent is None else parent.id, []):
            visit(node)
        if parent is None:
            # Invalid drafts remain inspectable; validation identifies unreachable/cyclic nodes.
            for node in sorted(nodes, key=lambda value: value.key):
                visit(node)
        definition = CollectionSnapshotDefinition(
            CollectionSnapshotResource.TARGET_NODES,
            version.owner_id,
            portfolio.broker_account_id,
            collection_filter_fingerprint(
                str(version.id), parent_node_id, version.content_digest or str(version.revision)
            ),
        )
        store = self._store(session)
        if query.cursor is None:
            page = store.materialize(definition, (node.id for node in ordered), limit=query.limit)
        else:
            page = store.resume(definition, cursor=query.cursor, limit=query.limit)
        values = {node.id: values_by_key[node.key] for node in ordered}
        return Page(
            tuple(app.TargetHierarchyNodeView(str(i), values[i]) for i in page.record_ids),
            page.next_cursor,
            page.limit,
            page.exact_total,
        )

    async def list_target_nodes(
        self,
        principal: Principal,
        version_id: str,
        *,
        parent_node_id: str | None,
        query: app.TargetPageQuery,
    ) -> Page[app.TargetHierarchyNodeView]:
        def execute(session: Session, _: UUID) -> Page[app.TargetHierarchyNodeView]:
            version = self._version(session, principal, version_id)
            portfolio = self._portfolio(session, principal, str(version.virtual_portfolio_id))
            return self._target_nodes_page(
                session, version, portfolio, parent_node_id=parent_node_id, query=query
            )

        return await self._run(principal, Scope.TARGETS_READ, execute)

    async def get_virtual_portfolio_targets(
        self,
        principal: Principal,
        portfolio_id: str,
        *,
        account_id: str | None,
        target_version_id: str | None,
        parent_node_id: str | None,
        query: app.TargetPageQuery,
    ) -> app.TargetPortfolioReadView:
        self._authorizer.require_scope(principal, Scope.PORTFOLIO_READ, now=self._now())

        def execute(session: Session, _: UUID) -> app.TargetPortfolioReadView:
            portfolio = self._portfolio(session, principal, portfolio_id)
            account = None if account_id is None else UUID(account_id)
            if portfolio.broker_account_id != account:
                raise _error(app.TargetServiceErrorCode.NOT_FOUND)
            portfolio_view = self._portfolio_view(session, portfolio)
            selected_id = target_version_id or portfolio_view.active_version_id
            if selected_id is None:
                if parent_node_id is not None or query.cursor is not None:
                    raise _error(app.TargetServiceErrorCode.NOT_FOUND)
                return app.TargetPortfolioReadView(
                    portfolio_view, None, Page((), None, query.limit, 0)
                )
            version = self._version(session, principal, selected_id)
            if version.virtual_portfolio_id != portfolio.id:
                raise _error(app.TargetServiceErrorCode.NOT_FOUND)
            version_view = self._version_view(session, version)
            nodes = self._target_nodes_page(
                session, version, portfolio, parent_node_id=parent_node_id, query=query
            )
            return app.TargetPortfolioReadView(portfolio_view, version_view, nodes)

        return await self._run(principal, Scope.TARGETS_READ, execute)

    async def compare_target_versions(
        self, principal: Principal, portfolio_id: str, left_version_id: str, right_version_id: str
    ) -> app.TargetVersionComparisonView:
        def execute(session: Session, _: UUID) -> app.TargetVersionComparisonView:
            portfolio = self._portfolio(session, principal, portfolio_id)
            left, right = (
                self._version(session, principal, left_version_id),
                self._version(session, principal, right_version_id),
            )
            if (
                left.virtual_portfolio_id != portfolio.id
                or right.virtual_portfolio_id != portfolio.id
            ):
                raise _error(app.TargetServiceErrorCode.NOT_FOUND)
            comparison = domain.compare_target_content(
                self._content(session, left),
                self._content(session, right),
                left_effective_at=left.effective_at,
                right_effective_at=right.effective_at,
            )
            return app.TargetVersionComparisonView(
                portfolio_id,
                left_version_id,
                right_version_id,
                left.effective_at,
                right.effective_at,
                comparison,
            )

        return await self._run(principal, Scope.TARGETS_READ, execute)
