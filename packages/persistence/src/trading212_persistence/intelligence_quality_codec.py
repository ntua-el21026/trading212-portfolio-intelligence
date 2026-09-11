"""Bounded lexical traversal, decoding only named status fields of retained results.

Skipped activity rows, source references, monetary values and counts are never
materialized as Python objects. The caller verifies the whole payload digest and
all physical permissions first. This is a private projection, not a result codec
replacement or a caller-configurable JSON-path API.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Literal

from trading212_application import intelligence_quality as q
from trading212_application.views import Availability, ViewQuality
from trading212_domain import historical_results as hr
from trading212_domain.planning import DriftCalculation, PlanningContext
from trading212_domain.xray import XrayMoneyMetric, XrayRatioMetric

_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_HEX = frozenset("0123456789abcdefABCDEF")
_RESULT_TYPES = {
    q.IntelligenceKind.PERFORMANCE: hr.PerformanceCalculation,
    q.IntelligenceKind.BENCHMARK: hr.BenchmarkCalculation,
    q.IntelligenceKind.INCOME: hr.IncomeCalculation,
    q.IntelligenceKind.ATTRIBUTION: hr.AttributionCalculation,
    q.IntelligenceKind.CASH_FLOW: hr.CashFlowCalculation,
}


class _Reader:
    def __init__(self, payload: bytes) -> None:
        if not 1 <= len(payload) <= 33_554_432:
            raise ValueError("Invalid quality document size.")
        self.text = payload.decode("utf-8")
        self.offset = 0
        self.nodes = 0
        self.depth = 0

    def _space(self) -> None:
        while self.offset < len(self.text) and self.text[self.offset] in " \t\r\n":
            self.offset += 1

    def _token(self, token: str) -> None:
        self._space()
        if not self.text.startswith(token, self.offset):
            raise ValueError("Invalid quality document structure.")
        self.offset += len(token)

    def _enter(self) -> None:
        self.nodes += 1
        self.depth += 1
        if self.nodes > 1_000_000 or self.depth > 32:
            raise ValueError("Quality document exceeds structural bounds.")

    def _string(self, *, decode: bool) -> str:
        self._space()
        start = self.offset
        self._token('"')
        while self.offset < len(self.text):
            char = self.text[self.offset]
            self.offset += 1
            if char == '"':
                if decode:
                    if self.offset - start > 2048:
                        raise ValueError("Quality metadata exceeds its bound.")
                    value = json.loads(self.text[start : self.offset])
                    if not isinstance(value, str):
                        raise ValueError("Invalid quality text.")
                    return value
                return ""
            if ord(char) < 32:
                raise ValueError("Invalid JSON string.")
            if char == "\\":
                if self.offset >= len(self.text):
                    break
                escape = self.text[self.offset]
                self.offset += 1
                if escape == "u":
                    digits = self.text[self.offset : self.offset + 4]
                    if len(digits) != 4 or any(char not in _HEX for char in digits):
                        raise ValueError("Invalid JSON escape.")
                    self.offset += 4
                elif escape not in '\\"/bfnrt':
                    raise ValueError("Invalid JSON escape.")
        raise ValueError("Unterminated JSON string.")

    def scalar(self) -> str | None:
        self._space()
        if self.text.startswith("null", self.offset):
            self.offset += 4
            return None
        return self._string(decode=True)

    def object(
        self, handlers: dict[str, Callable[[], None]], *, keys: set[str] | None = None
    ) -> None:
        self._enter()
        self._token("{")
        seen: set[str] = set()
        self._space()
        if self.text.startswith("}", self.offset):
            self.offset += 1
        else:
            while True:
                key = self._string(decode=True)
                if key in seen or (keys is not None and key not in keys):
                    raise ValueError("Duplicate or unknown quality document field.")
                seen.add(key)
                if len(seen) > 256:
                    raise ValueError("Quality object exceeds its bound.")
                self._token(":")
                handler = handlers.get(key)
                if handler is None:
                    self.skip()
                else:
                    handler()
                self._space()
                if self.text.startswith("}", self.offset):
                    self.offset += 1
                    break
                self._token(",")
        self.depth -= 1
        if keys is not None and seen != keys:
            raise ValueError("Missing quality document field.")

    def skip(self) -> None:
        self._space()
        self._enter()
        if self.offset >= len(self.text):
            raise ValueError("Incomplete quality document.")
        leading_char = self.text[self.offset]
        if leading_char == "{":
            self.depth -= 1
            self.object({})
            return
        if leading_char == "[":
            self.offset += 1
            self._space()
            if self.text.startswith("]", self.offset):
                self.offset += 1
            else:
                while True:
                    self.skip()
                    self._space()
                    if self.text.startswith("]", self.offset):
                        self.offset += 1
                        break
                    self._token(",")
        elif leading_char == '"':
            self._string(decode=False)
        else:
            for literal in ("true", "false", "null"):
                if self.text.startswith(literal, self.offset):
                    self.offset += len(literal)
                    break
            else:
                match = _NUMBER.match(self.text, self.offset)
                if match is None:
                    raise ValueError("Invalid JSON scalar.")
                self.offset = match.end()
        self.depth -= 1

    def finish(self) -> None:
        self._space()
        if self.offset != len(self.text) or self.depth != 0:
            raise ValueError("Trailing quality document data.")


@dataclass(frozen=True, slots=True)
class RecordedStatus:
    key: str
    availability: Availability
    quality: ViewQuality
    basis: Literal["metric", "result_context"]
    reason: str | None


@dataclass(frozen=True, slots=True)
class StatusDocument:
    account_id: str | None
    input_digest: str | None
    metrics: tuple[RecordedStatus, ...]


def status_document(payload: bytes, kind: q.IntelligenceKind) -> StatusDocument:
    """Only nine fixed producer shapes are reachable; valuation uses scalar SQL."""
    reader = _Reader(payload)
    context: dict[str, str | None] = {}
    envelope: dict[str, str | None] = {}
    metrics: dict[str, dict[str, str | None]] = {}
    present: dict[str, bool] = {}
    native_fields = {field.name for field in fields(hr.HistoricalResultContext)}
    planning = kind in {q.IntelligenceKind.ACTUAL_VS_TARGET, q.IntelligenceKind.DRIFT}

    def scalar_handler(target: dict[str, str | None], key: str) -> Callable[[], None]:
        def read_scalar() -> None:
            target[key] = reader.scalar()

        return read_scalar

    def keyed_handler(handler: Callable[[str], None], key: str) -> Callable[[], None]:
        def read_key() -> None:
            handler(key)

        return read_key

    def context_fields() -> None:
        names = {"account_id", "input_digest", "quality", "availability"}
        if planning:
            names.add("reason_code")
        reader.object(
            {key: scalar_handler(context, key) for key in names},
            keys={field.name for field in fields(PlanningContext)} if planning else native_fields,
        )

    def metric(key: str) -> None:
        values: dict[str, str | None] = {}
        names = {
            "availability",
            "quality",
            "reason" if kind is q.IntelligenceKind.XRAY else "reason_code",
        }
        if kind is q.IntelligenceKind.XRAY:
            expected = {
                field.name
                for field in fields(XrayMoneyMetric if key == "total" else XrayRatioMetric)
            }
        else:
            expected = {"value", "availability", "reason_code", "quality", "coverage_key", "origin"}
        handlers: dict[str, Callable[[], None]] = {
            name: scalar_handler(values, name) for name in names
        }
        handlers["value"] = keyed_handler(presence, key)
        reader.object(handlers, keys=expected)
        metrics[key] = values

    inherited = {
        q.IntelligenceKind.BENCHMARK: {"paired_observation_count", "comparable_total_return_basis"},
        q.IntelligenceKind.INCOME: {"event_count"},
        q.IntelligenceKind.CASH_FLOW: set(q.METRIC_KEYS[q.IntelligenceKind.CASH_FLOW]),
        q.IntelligenceKind.XRAY: {"top_concentrations", "thresholds", "quality_coverage"},
    }.get(kind, set())

    def presence(key: str) -> None:
        reader._space()
        present[key] = not reader.text.startswith("null", reader.offset)
        reader.skip()

    def summary_fields() -> None:
        reader.object(
            {
                key: keyed_handler(presence if planning or key in inherited else metric, key)
                for key in q.METRIC_KEYS[kind]
            },
            keys=set(q.METRIC_KEYS[kind]),
        )

    if kind is q.IntelligenceKind.XRAY:
        reader.object(
            {
                "component": lambda: envelope.__setitem__("component", reader.scalar()),
                "schema_version": lambda: envelope.__setitem__("schema_version", reader.scalar()),
                "value": summary_fields,
            },
            keys={"component", "schema_version", "value"},
        )
        if envelope != {"component": "XrayPortfolioSummary", "schema_version": "1"}:
            raise ValueError("Invalid retained X-ray component identity.")
    else:
        root = DriftCalculation if planning else _RESULT_TYPES[kind]
        handlers = {"context": context_fields, "totals" if planning else "summary": summary_fields}
        if not planning:
            handlers["family"] = lambda: envelope.__setitem__("family", reader.scalar())
        reader.object(handlers, keys={field.name for field in fields(root)})
        if not planning and envelope.get("family") != (
            "cash_flows" if kind is q.IntelligenceKind.CASH_FLOW else kind.value
        ):
            raise ValueError("Invalid retained historical family.")
    reader.finish()
    output = []
    for key in q.METRIC_KEYS[kind]:
        values = metrics.get(key)
        basis: Literal["metric", "result_context"] = "metric"
        if values is None:
            basis = "result_context"
            values = metrics["total"] if kind is q.IntelligenceKind.XRAY else context
        quality_text = values["quality"]
        if not isinstance(quality_text, str):
            raise ValueError("Recorded quality must be a known state.")
        quality = ViewQuality(quality_text)
        recorded = values["availability"]
        if not isinstance(recorded, str):
            raise ValueError("Recorded availability must be a known state.")
        availability = Availability.UNAVAILABLE if recorded == "failed" else Availability(recorded)
        if recorded == "failed":
            quality = ViewQuality.FAILED
        if basis == "metric" and present[key] == (availability is Availability.UNAVAILABLE):
            raise ValueError("Recorded metric value presence and availability disagree.")
        if planning and not present[key]:
            availability = Availability.UNAVAILABLE
        output.append(
            RecordedStatus(
                key, availability, quality, basis, values.get("reason", values.get("reason_code"))
            )
        )
    return StatusDocument(context.get("account_id"), context.get("input_digest"), tuple(output))
