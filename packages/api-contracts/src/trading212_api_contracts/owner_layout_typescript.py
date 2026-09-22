"""Five fixed preferences operations, generated separately from all older clients."""

from typing import Any

from .typescript import TargetClientGenerator

OWNER_LAYOUT_OPERATIONS = frozenset(
    {
        ("get", "/api/v1/preferences/layouts", "list_owner_layouts"),
        ("post", "/api/v1/preferences/layouts", "create_owner_layout"),
        ("get", "/api/v1/preferences/layouts/{layout_id}", "get_owner_layout"),
        ("patch", "/api/v1/preferences/layouts/{layout_id}", "update_owner_layout"),
        ("post", "/api/v1/preferences/layouts/{layout_id}/archive", "archive_owner_layout"),
    }
)


class OwnerLayoutClientGenerator(TargetClientGenerator):
    def __init__(self, contract: dict[str, Any]) -> None:
        super().__init__(contract, tag="owner-layouts")

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
            rendered = rendered.replace(f"Target{name}", f"OwnerLayout{name}")
        return rendered.replace("./target-transport", "./owner-layout-transport").replace(
            "OwnerLayoutTransport, type", "OwnerLayoutTransport, OwnerLayoutApiError, type"
        )


def render_owner_layout_client(contract: dict[str, Any]) -> str:
    actual = [
        (method, path, operation["operationId"])
        for path, methods in contract["paths"].items()
        for method, operation in methods.items()
        if "owner-layouts" in operation.get("tags", [])
    ]
    if len(actual) != len(OWNER_LAYOUT_OPERATIONS) or set(actual) != OWNER_LAYOUT_OPERATIONS:
        raise ValueError("The fixed owner layout operation registry differs.")
    return OwnerLayoutClientGenerator(contract).render()
