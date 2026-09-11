"""Current licensed full-run access for ephemeral company planning projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session
from trading212_application.planning import PlanningServiceError, PlanningServiceErrorCode
from trading212_application.sources import SourceServiceError, SourceServiceErrorCode
from trading212_application.xray import XrayServiceError, XrayServiceErrorCode
from trading212_domain.sources import SourceLicense, SourceUse
from trading212_domain.xray import XrayInput
from trading212_domain.xray_codec import decode_xray_input
from trading212_domain.xray_result import XrayCalculation
from trading212_security.principals import Principal, Scope

from .xray_service import PostgresXrayService
from .xray_store_contract import XrayRunHandle


@dataclass(frozen=True, slots=True)
class SelectedCompanyBasis:
    handle: XrayRunHandle
    value: XrayInput
    result: XrayCalculation


class PlanningCompanyStore(PostgresXrayService):
    """Reuse physical/source guards; require STORE before the first decode too.

    Callers hold sources then xray owner locks for the entire planning read.
    required_copy_use=REPORT/EXPORT additionally activates the existing copy
    permissions for a future report integration; this class persists no copy.
    """

    def _permit(
        self, session: Session, owner: UUID, license_id: UUID, use: SourceUse
    ) -> SourceLicense:
        license = super()._permit(session, owner, license_id, use)
        if use is not SourceUse.STORE:
            super()._permit(session, owner, license_id, SourceUse.STORE)
        return license

    def load_selected(
        self,
        session: Session,
        principal: Principal,
        account_id: UUID,
        run_id: UUID,
        *,
        available_by: datetime | None = None,
    ) -> SelectedCompanyBasis:
        """No resolve/create/latest-run path; consumer cutoff is optional and exact."""
        self._authorizer.require_scope(principal, Scope.ANALYTICS_READ, now=self._now())
        try:
            run, capture, _ = self._authorized_rows(session, principal, account_id, run_id)
            if available_by is not None and (
                run.calculated_at > available_by
                or run.sealed_at is None
                or run.sealed_at > available_by
                or capture.sealed_at is None
                or capture.sealed_at > available_by
            ):
                raise XrayServiceError(
                    XrayServiceErrorCode.INPUT_SNAPSHOT_MISMATCH,
                    "The pinned basis was not available at the consumer cutoff.",
                )
            handle = self._authorize_xray_run(session, principal, account_id, run_id)
            result = self._load_xray_result(session, principal, account_id, handle)
            # _load_xray_result already verified these exact bytes, their digest,
            # physical parent/child dependencies, result kind and envelope pins.
            value = decode_xray_input(capture.canonical_input)
            return SelectedCompanyBasis(handle, value, result)
        except (SourceServiceError, XrayServiceError) as exc:
            code = (
                PlanningServiceErrorCode.NOT_FOUND
                if exc.code in {SourceServiceErrorCode.NOT_FOUND, XrayServiceErrorCode.NOT_FOUND}
                else PlanningServiceErrorCode.ACCESS_DENIED
                if exc.code
                in {SourceServiceErrorCode.ACCESS_DENIED, XrayServiceErrorCode.ACCESS_DENIED}
                else PlanningServiceErrorCode.RESULT_TOO_LARGE
                if exc.code
                in {SourceServiceErrorCode.RESULT_TOO_LARGE, XrayServiceErrorCode.RESULT_TOO_LARGE}
                else PlanningServiceErrorCode.PLANNING_UNAVAILABLE
            )
            raise PlanningServiceError(code, "The selected company basis is unavailable.") from None
