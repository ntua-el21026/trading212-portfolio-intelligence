"""Shared internal contract between X-ray run storage and the public-read facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session
from trading212_application.xray import XrayContext, XrayRunRequest, XraySourceReferenceView
from trading212_domain.xray_result import XrayCalculation, XrayPortfolioSummary
from trading212_security.principals import Principal


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayRunHandle:
    run_id: UUID
    input_id: UUID
    context: XrayContext
    summary: XrayPortfolioSummary


class XrayRunAccess(Protocol):
    def _resolve_xray_run(
        self,
        session: Session,
        principal: Principal,
        account_id: UUID,
        request: XrayRunRequest,
        *,
        retained_run_id: UUID | None = None,
    ) -> XrayRunHandle: ...

    def _authorize_xray_run(
        self,
        session: Session,
        principal: Principal,
        account_id: UUID,
        run_id: UUID,
    ) -> XrayRunHandle: ...

    def _load_xray_result(
        self,
        session: Session,
        principal: Principal,
        account_id: UUID,
        handle: XrayRunHandle,
    ) -> XrayCalculation: ...

    def _xray_source_views(
        self,
        session: Session,
        owner: UUID,
        handle: XrayRunHandle,
        reference_ids: tuple[UUID, ...],
    ) -> tuple[XraySourceReferenceView, ...]: ...
