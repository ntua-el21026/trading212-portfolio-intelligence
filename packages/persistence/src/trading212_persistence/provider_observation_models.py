"""Immutable owner/provider observations; no account or response payload is invented."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, Identity, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .source_models import SourceOwned, owned, owner_fk
from .types import UTCDateTime

PROVIDER_CAPABILITIES = (
    "'price_history','corporate_actions','fx_rates','benchmark_series',"
    "'resolve_instrument','classifications','constituents'"
)
PROVIDER_FAILURES = (
    "'not_configured','unsupported','not_found','authentication_failed','access_denied',"
    "'rate_limited','timeout','transient_failure','invalid_schema','pagination_invalid',"
    "'license_denied','payload_too_large','permanent_failure'"
)


class ProviderInvocationObservationModel(SourceOwned):
    __tablename__ = "provider_invocation_observations"
    __table_args__ = (
        owned(),
        owner_fk("provider_id", "market_data_providers"),
        UniqueConstraint("observed_sequence"),
        CheckConstraint(f"capability IN ({PROVIDER_CAPABILITIES})", name="capability_allowed"),
        CheckConstraint(
            f"failure_code IS NULL OR failure_code IN ({PROVIDER_FAILURES})", name="failure_allowed"
        ),
        CheckConstraint(
            "started_at <= completed_at AND completed_at <= first_known_at", name="chronology"
        ),
        CheckConstraint("outcome IN ('succeeded','failed','unavailable')", name="outcome_allowed"),
        CheckConstraint("(outcome='succeeded') = (failure_code IS NULL)", name="success_state"),
        CheckConstraint(
            "(outcome='unavailable') = (failure_code IN "
            "('not_configured','unsupported','license_denied')) OR failure_code IS NULL",
            name="unavailable_state",
        ),
        Index(
            "ix_provider_invocation_cutoff",
            "owner_id",
            "provider_id",
            "completed_at",
            "observed_sequence",
        ),
    )
    provider_id: Mapped[UUID] = mapped_column()
    observed_sequence: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    capability: Mapped[str] = mapped_column(String(40))
    adapter_version: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    first_known_at: Mapped[datetime] = mapped_column(UTCDateTime())
    outcome: Mapped[str] = mapped_column(String(20))
    failure_code: Mapped[str | None] = mapped_column(String(40))


PROVIDER_OBSERVATION_MODELS = (ProviderInvocationObservationModel,)
