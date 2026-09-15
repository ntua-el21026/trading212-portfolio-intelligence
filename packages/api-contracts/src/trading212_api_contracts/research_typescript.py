"""Eight fixed research operations with unchanged shared source schemas."""

from __future__ import annotations

from typing import Any

from .typescript import TargetClientGenerator

RESEARCH_OPERATIONS = frozenset(
    {
        ("get", "/api/v1/accounts/{account_id}/research", "get_research_summary"),
        ("get", "/api/v1/research/items/{item_id}", "get_research_item"),
        ("get", "/api/v1/accounts/{account_id}/research/notes", "list_research_notes"),
        ("post", "/api/v1/accounts/{account_id}/research/notes", "create_research_note"),
        ("get", "/api/v1/research/notes/{note_id}", "get_research_note"),
        ("get", "/api/v1/research/notes/{note_id}/versions", "list_research_note_versions"),
        ("post", "/api/v1/research/notes/{note_id}/versions", "create_research_note_version"),
        ("post", "/api/v1/research/events/{event_id}/review", "review_research_event"),
    }
)


class ResearchClientGenerator(TargetClientGenerator):
    def __init__(self, contract: dict[str, Any]) -> None:
        source = TargetClientGenerator(contract, tag="sources")
        source.render()
        super().__init__(contract, tag="research", imported_schemas=frozenset(source.rendered))

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
            rendered = rendered.replace(f"Target{name}", f"Research{name}")
        return rendered.replace("./target-transport", "./research-transport").replace(
            "ResearchTransport, type", "ResearchTransport, ResearchApiError, type"
        )


def render_research_client(contract: dict[str, Any]) -> str:
    actual = [
        (method, path, operation["operationId"])
        for path, methods in contract["paths"].items()
        for method, operation in methods.items()
        if "research" in operation.get("tags", [])
    ]
    if len(actual) != len(RESEARCH_OPERATIONS) or set(actual) != RESEARCH_OPERATIONS:
        raise ValueError("The frozen research operation registry differs.")
    return ResearchClientGenerator(contract).render()
