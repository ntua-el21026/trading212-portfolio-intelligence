"""Material-input quality propagation helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from trading212_domain import Coverage, DataQuality, DomainWarning, Instant, QualityState

_SEVERITY = {
    QualityState.FRESH: 0,
    QualityState.STALE: 1,
    QualityState.ESTIMATED: 2,
    QualityState.PARTIAL: 3,
    QualityState.UNRECONCILED: 4,
    QualityState.FAILED: 5,
}


def combine_quality(states: Iterable[QualityState]) -> QualityState:
    material = tuple(states)
    if not material:
        return QualityState.FRESH
    return max(material, key=_SEVERITY.__getitem__)


def degrade_quality(current: QualityState, limitation: QualityState) -> QualityState:
    return combine_quality((current, limitation))


def build_quality(
    *,
    state: QualityState,
    evaluated_at: Instant,
    coverage: Coverage,
    warnings: tuple[DomainWarning, ...] = (),
    missing_inputs: tuple[str, ...] = (),
    freshness_threshold_seconds: int | None = None,
) -> DataQuality:
    return DataQuality(
        state=state,
        evaluated_at=evaluated_at,
        freshness_threshold_seconds=freshness_threshold_seconds,
        coverage=coverage,
        warnings=warnings,
        missing_inputs=missing_inputs,
    )


@dataclass(frozen=True, slots=True)
class QualityInputs:
    states: tuple[QualityState, ...]
    forced_limitation: QualityState | None = None

    def evaluate(self) -> QualityState:
        state = combine_quality(self.states)
        if self.forced_limitation is not None:
            state = degrade_quality(state, self.forced_limitation)
        return state
