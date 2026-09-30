"""Six fixed aggregate operations using the existing bounded shared transport."""

from __future__ import annotations

from typing import Any

from .typescript import TargetClientGenerator

AGGREGATE_OPERATIONS = frozenset(
    {
        ("get", "/api/v1/aggregate-selections", "list_aggregate_selections"),
        ("post", "/api/v1/aggregate-selections", "create_aggregate_selection"),
        ("get", "/api/v1/aggregate-selections/{selection_id}", "get_aggregate_selection"),
        ("get", "/api/v1/aggregate-selections/{selection_id}/runs", "list_aggregate_runs"),
        ("post", "/api/v1/aggregate-selections/{selection_id}/runs", "create_aggregate_run"),
        ("get", "/api/v1/aggregate-runs/{run_id}", "get_aggregate_run"),
    }
)


class AggregateClientGenerator(TargetClientGenerator):
    def __init__(self, contract: dict[str, Any]) -> None:
        source = TargetClientGenerator(contract, tag="sources")
        source.render()
        super().__init__(contract, tag="aggregate", imported_schemas=frozenset(source.rendered))

    def render(self) -> str:
        rendered = super().render()
        for name in (
            "Transport",
            "ApiClient",
            "ApiResponse",
            "ReadOptions",
            "CommandOptions",
            "ClientOptions",
        ):
            rendered = rendered.replace(f"Target{name}", f"Aggregate{name}")
        return rendered.replace("./target-transport", "./aggregate-transport").replace(
            "AggregateTransport, type", "AggregateTransport, AggregateApiError, type"
        )


def render_aggregate_client(contract: dict[str, Any]) -> str:
    actual = [
        (method, path, operation["operationId"])
        for path, methods in contract["paths"].items()
        for method, operation in methods.items()
        if "aggregate" in operation.get("tags", [])
    ]
    if len(actual) != len(AGGREGATE_OPERATIONS) or set(actual) != AGGREGATE_OPERATIONS:
        raise ValueError("The frozen aggregate operation registry differs.")
    return AggregateClientGenerator(contract).render()
