"""Immutable account policy registration through the shared typed policy codec."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from trading212_application.xray import XrayServiceErrorCode
from trading212_application.xray_ingestion import XrayPolicyRegistration, XrayRegistrationReceipt
from trading212_domain.xray_codec import encode_xray_policy
from trading212_security.principals import Principal

from .xray_base import xray_error
from .xray_catalog_models import XrayPolicyTaxonomyModel, XrayPolicyVersionModel, XrayTaxonomyModel
from .xray_ingestion_store import receipt
from .xray_registrations import XrayRegistrations


class XrayPolicyRegistrations(XrayRegistrations):
    async def register_xray_policy(
        self,
        principal: Principal,
        account_id: str,
        registration: XrayPolicyRegistration,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> XrayRegistrationReceipt:
        if not isinstance(registration, XrayPolicyRegistration):
            raise xray_error(XrayServiceErrorCode.VALIDATION_FAILED)
        canonical = encode_xray_policy(registration.policy)
        if len(canonical) > 2_097_152:
            raise xray_error(XrayServiceErrorCode.RESULT_TOO_LARGE)
        content = hashlib.sha256(canonical).hexdigest()

        def operation(session: Session, owner: UUID) -> XrayRegistrationReceipt:
            account = self._account(session, principal, account_id)
            if account is None:
                raise xray_error(XrayServiceErrorCode.NOT_FOUND)
            kind = "policy.register"
            previous, fingerprint = self._command(
                session, owner, kind, idempotency_key, correlation_id, (account_id, registration)
            )
            row = session.scalar(
                select(XrayPolicyVersionModel).where(
                    XrayPolicyVersionModel.owner_id == owner,
                    XrayPolicyVersionModel.account_id == account,
                    XrayPolicyVersionModel.key == registration.key,
                    XrayPolicyVersionModel.version == registration.policy.version,
                )
            )
            if previous is not None:
                row = self._owned(session, owner, XrayPolicyVersionModel, previous.result_id)
            if row is not None:
                if (
                    row.account_id != account
                    or row.id != registration.policy.id
                    or row.key != registration.key
                    or row.content_digest != content
                    or row.effective_at != registration.effective_at
                ):
                    raise xray_error(XrayServiceErrorCode.SOURCE_REVISION_CONFLICT)
                if previous is not None:
                    return receipt(row)
            else:
                for declared in registration.taxonomies:
                    existing = session.scalar(
                        select(XrayTaxonomyModel).where(
                            XrayTaxonomyModel.owner_id == owner,
                            XrayTaxonomyModel.id == UUID(declared.id),
                        )
                    )
                    if existing is not None:
                        if (existing.key, existing.version, existing.dimension) != (
                            declared.key,
                            declared.version,
                            declared.dimension.value,
                        ):
                            raise xray_error(XrayServiceErrorCode.SOURCE_REVISION_CONFLICT)
                    else:
                        session.add(
                            XrayTaxonomyModel(
                                id=UUID(declared.id),
                                owner_id=owner,
                                key=declared.key,
                                version=declared.version,
                                dimension=declared.dimension.value,
                                created_at=self._now(),
                            )
                        )
                observed = self._now()
                row = XrayPolicyVersionModel(
                    id=registration.policy.id,
                    owner_id=owner,
                    account_id=account,
                    key=registration.key,
                    version=registration.policy.version,
                    effective_at=registration.effective_at,
                    first_observed_at=observed,
                    canonical_policy=canonical,
                    content_digest=content,
                    created_at=observed,
                )
                session.add(row)
                session.flush()
                session.add_all(
                    XrayPolicyTaxonomyModel(
                        owner_id=owner,
                        policy_id=row.id,
                        taxonomy_id=UUID(item.id),
                        created_at=observed,
                    )
                    for item in registration.taxonomies
                )
                session.flush()
            return self._command_receipt(
                session, principal, kind, idempotency_key, fingerprint, correlation_id, row
            )

        return await self._xrun(principal, operation, write=True)
