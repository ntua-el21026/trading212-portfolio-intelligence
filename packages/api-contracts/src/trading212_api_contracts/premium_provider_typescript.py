"""The one frozen premium provider status operation."""

from typing import Any

from .typescript import TargetClientGenerator


class PremiumProviderClientGenerator(TargetClientGenerator):
    def __init__(self, contract: dict[str, Any]) -> None:
        super().__init__(contract, tag="premium-providers")

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
            rendered = rendered.replace(f"Target{name}", f"PremiumProvider{name}")
        return rendered.replace("./target-transport", "./premium-provider-transport").replace(
            "PremiumProviderTransport, type",
            "PremiumProviderTransport, PremiumProviderApiError, type",
        )


def render_premium_provider_client(contract: dict[str, Any]) -> str:
    actual = [
        (method, path, operation["operationId"])
        for path, methods in contract["paths"].items()
        for method, operation in methods.items()
        if "premium-providers" in operation.get("tags", [])
    ]
    if actual != [
        ("get", "/api/v1/accounts/{account_id}/premium-providers", "get_premium_provider_status")
    ]:
        raise ValueError("The fixed provider status operation registry differs.")
    return PremiumProviderClientGenerator(contract).render()
