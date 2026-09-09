"""Bounded typed synthetic constituent and classification replay; no network transport."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from trading212_application import source_providers as ports
from trading212_domain.serialization import canonical_json
from trading212_domain.source_details import ClassificationObservation, ConstituentHolding
from trading212_domain.sources import (
    SourceLicense,
    SourceProvenance,
    SourceUse,
    source_id,
    source_tuple,
)
from trading212_domain.values import require_utc

from .replay_runtime import ReplayFault, ReplayRuntime, ReplayWindow


@dataclass(frozen=True, slots=True, kw_only=True)
class XrayReplayFund:
    mapping_id: str
    effective_at: datetime
    holdings: tuple[ConstituentHolding, ...]
    stated_coverage: Decimal
    unresolved_weight: Decimal
    cash_weight: Decimal

    def __post_init__(self) -> None:
        source_id(self.mapping_id)
        object.__setattr__(self, "effective_at", require_utc(self.effective_at))
        source_tuple(self.holdings, ConstituentHolding, "holdings", 100_000)
        if len({row.source_key for row in self.holdings}) != len(self.holdings):
            raise ValueError("Synthetic constituent source keys must be unique.")


class XrayReplayProvider:
    """A trusted fixture binds actual canonical IDs before any provider request."""

    def __init__(
        self,
        *,
        owner_id: str,
        license: SourceLicense,
        known_at: datetime,
        funds: tuple[XrayReplayFund, ...],
        classifications: tuple[ClassificationObservation, ...],
        clock: Callable[[], datetime],
        runtime: ReplayRuntime | None = None,
    ) -> None:
        source_id(owner_id)
        source_tuple(funds, XrayReplayFund, "funds", 256)
        source_tuple(classifications, ClassificationObservation, "classifications", 100_000)
        if len({fund.mapping_id for fund in funds}) != len(funds):
            raise ValueError("Synthetic fund mappings must be unique.")
        self.owner_id = owner_id
        self.license = license
        self.known_at = require_utc(known_at)
        self.clock = clock
        self.funds = funds
        self.classifications = classifications
        self.runtime = runtime or ReplayRuntime(
            cursor_key=hashlib.sha256(b"synthetic-xray-replay-v1").digest()
        )
        self.data_digest = hashlib.sha256(
            canonical_json((funds, classifications)).encode()
        ).hexdigest()

    def _failure(
        self, capability: ports.SourceCapability, code: ports.SourceProviderError
    ) -> ports.SourceFailure:
        return ports.SourceFailure(
            code=code,
            capability=capability,
            provider_key="synthetic-xray",
            retryable=False,
            correlation_id="synthetic-xray-replay-v1",
        )

    def _provenance(self, effective_at: datetime) -> SourceProvenance:
        return SourceProvenance(
            provider_id=self.license.provider_id,
            license_version_id=self.license.id,
            adapter_version="synthetic-xray-replay-v1",
            schema_version="xray-fixture-v1",
            source_revision="synthetic-xray-1",
            revision_order=1,
            effective_at=effective_at,
            first_observed_at=self.known_at,
            synthetic=True,
        )

    def _check(
        self, capability: ports.SourceCapability, cutoff: datetime
    ) -> ports.SourceFailure | None:
        if not self.license.permits(SourceUse.STORE):
            return self._failure(capability, ports.SourceProviderError.LICENSE_DENIED)
        if (
            self.license.effective_at > self.known_at
            or cutoff < self.known_at
            or require_utc(self.clock()) < self.known_at
        ):
            return self._failure(capability, ports.SourceProviderError.NOT_FOUND)
        return None

    async def _window(
        self,
        request: ports.ClassificationRequest | ports.ConstituentRequest,
        capability: ports.SourceCapability,
        count: int,
    ) -> ReplayWindow | ports.SourceFailure:
        scope = canonical_json(
            (self.owner_id, self.license.id, self.data_digest, replace(request, continuation=None))
        )
        window = self.runtime.window(scope=scope, count=count, continuation=request.continuation)
        if isinstance(window, ReplayFault):
            return self._failure(capability, ports.SourceProviderError(window.value))
        outcome = await self.runtime.run_attempts(deadline=window.deadline)
        if outcome is not ReplayFault.NONE:
            return self._failure(capability, ports.SourceProviderError(outcome.value))
        return window

    async def get_constituents(
        self, request: ports.ConstituentRequest
    ) -> ports.ConstituentPage | ports.SourceFailure:
        capability = ports.SourceCapability.CONSTITUENTS
        failure = self._check(capability, request.source_cutoff_at)
        if failure is not None:
            return failure
        fund = next(
            (item for item in self.funds if item.mapping_id == request.fund_series_id), None
        )
        if fund is None or fund.effective_at > request.effective_at:
            return self._failure(capability, ports.SourceProviderError.NOT_FOUND)
        window = await self._window(request, capability, len(fund.holdings))
        if isinstance(window, ports.SourceFailure):
            return window
        return ports.ConstituentPage(
            request=request,
            provenance=self._provenance(fund.effective_at),
            effective_at=fund.effective_at,
            holdings=fund.holdings[window.start : window.stop],
            stated_coverage=fund.stated_coverage,
            unresolved_weight=fund.unresolved_weight,
            cash_weight=fund.cash_weight,
            continuation=window.continuation,
        )

    async def get_classifications(
        self, request: ports.ClassificationRequest
    ) -> ports.ClassificationPage | ports.SourceFailure:
        capability = ports.SourceCapability.CLASSIFICATIONS
        failure = self._check(capability, request.source_cutoff_at)
        if failure is not None:
            return failure
        observations = tuple(
            row
            for row in self.classifications
            if row.instrument_id in request.instrument_ids
            and row.taxonomy == request.taxonomy
            and row.taxonomy_version == request.taxonomy_version
        )
        if not observations:
            return self._failure(capability, ports.SourceProviderError.NOT_FOUND)
        window = await self._window(request, capability, len(observations))
        if isinstance(window, ports.SourceFailure):
            return window
        return ports.ClassificationPage(
            request=request,
            provenance=self._provenance(max(row.valid_from for row in observations)),
            observations=observations[window.start : window.stop],
            continuation=window.continuation,
        )
