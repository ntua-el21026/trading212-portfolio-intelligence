"""Closed private execution envelope; operational fields never enter the financial digest."""

from dataclasses import dataclass
from datetime import datetime

from .errors import fail_validation
from .historical import HistoricalInput, historical_digest
from .risk import RiskDefinitionContent
from .risk_history import RiskAssetSource
from .sources import source_tuple
from .values import require_utc
from .xray_result import XrayCalculation


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskExecutionInput:
    historical: HistoricalInput
    definition: RiskDefinitionContent
    assets: tuple[RiskAssetSource, ...]
    xray: XrayCalculation | None
    input_digest: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.historical, HistoricalInput) or not isinstance(
            self.definition, RiskDefinitionContent
        ):
            fail_validation("Canonical risk execution input is required.", field="input")
        source_tuple(self.assets, RiskAssetSource, "assets", 32)
        if self.xray is not None and not isinstance(self.xray, XrayCalculation):
            fail_validation("Canonical X-ray result is required.", field="xray")
        historical_digest(self.input_digest, "input_digest")
        require_utc(self.expires_at)
