"""Preserve complete Phase 2 tool descriptors through premium report versioning."""

import hashlib
import json

import pytest
from trading212_mcp.server import create_runtime
from trading212_security.settings import RuntimeEnvironment, SecuritySettings

pytestmark = pytest.mark.contract
# Captured before premium report changes at immutable source:
# 4d747f6c1281a2914c84f18a02554c18f612e249.
# Hashes bind complete descriptors, including transitive input/output $defs, scopes and annotations.
# Original descriptor JSON is retained in the Phase 3 portable component evidence.
EXPECTED = {
    "get_account_summary": "6a442c53410a4ae4ebcbba338e1d31d49a4dca8600a20b3ade027d660be620d8",
    "get_portfolio_snapshot": "aaaf2e4363efa60c82aeac25cc3978735718c9e8800f1a44538c655085ca5143",
    "list_positions": "524fa349e56b1456efbac8f40cd9355222dc6436f8e074e65a95bcda39576614",
    "list_recent_transactions": "c045e6737c13d0bb4edac4ae5d1ff3badfdfb7be56ecbb967244daef7f7d06e4",
    "get_dividend_summary": "413a6b80dc8d3fb15a9bc6d7cb93f66940643827596528d240975923d91b43f4",
    "get_direct_allocation": "0f099fd2645295942340b9a9b7308f9f2c8bd5fba9c1e36976713a7d424f8674",
    "compare_portfolio_snapshots": (
        "257c01b72fa61a553ff0d37d4e6659dbcd0798a3e12fadd1a8b8446932bca84e"
    ),
    "get_reconciliation_status": "e42586aaca84a72b01749be09b3cb85c75000ca0921791dcb418ff145504edf4",
    "get_data_quality_summary": "4d4a876e9da0ed1c50cefc172fcf305f332706261a17006aa322df8bf3531011",
    "list_virtual_pies": "a4ccf472ba3f135058f46796b6e4f2411a5775e7c2f5808e7d677b219ff11e37",
    "get_virtual_pie": "7d614c68ad6b722b4d7bff3b74c008471c87b079647953bc59b5d5c13e0accd0",
    "get_actual_vs_target": "2974808abfdf70cfdc34397b8804c60c8242a10dfbac8861901aaeba1aefbce8",
    "get_drift_analysis": "34184c201ddb958ebe0d2d33ee4f055aa1a0b67fb3ba081524586c59d0709a37",
    "get_contribution_plan": "55a2bb3ef637c6538a22eecc93af5a5ea5b389e33a45ba8e0361b869c13fb67d",
    "create_contribution_plan": "139ab2fe7d03b5fb0fae7b347a0981534ad80de43c293d7775f558fb73d16ece",
    "get_performance_summary": "0f8d797b00fca0deba862dc7a0207b3b19eac4b9f0949680e497cc1020ccbe67",
    "get_benchmark_comparison": "2ff625aff7c319283f3856e4ea889210564832901538f21ff63ed26baf4fd29a",
    "get_dividend_intelligence": "b1dad4ba1e3c39ea7cdad6db5b4b1cfea9025f712492f4ffebc2fa14b6c7d254",
    "get_attribution_summary": "fbd2a1fed7ee968428f779c40c66aa27f1ac743b574e12b9d01fff6acf92e42f",
    "get_effective_exposure": "d5437d829a6517b558f4f01f4e9f711d856762082f223bd914253344cc367aba",
    "get_etf_overlap": "7b49c7474c0e40d73e06fc7d0604107adef506ad3e39ba1e744ca1ac9444d78b",
    "get_report_status": "c8558b2f4996d917dc9573741d284cfdef2f4c124292e3da1434fd20d00d2873",
    "list_reports": "6ea502a4f051689a4035f1ad9252c846f49d95f56e66563651e4235843dee110",
    "generate_portfolio_report": "91326f339f879c956b2345374cf3bc2642f3a8d2b0b1aa06b3c1759b2ce37d04",
    "get_alert_summary": "d5c9f478bce19b5dab592f7041cba315e42194b420056225152747b17dc125eb",
}


async def test_original_25_complete_tool_descriptors_remain_unchanged() -> None:
    server = create_runtime(
        security_settings=SecuritySettings(
            environment=RuntimeEnvironment.TEST, local_synthetic_auth_enabled=True
        )
    ).server
    tools = await server.list_tools()
    assert tuple(tool.name for tool in tools[:25]) == tuple(EXPECTED)
    for tool in tools[:25]:
        descriptor = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
        # The accepted Phase 3 registry authorizes precisely these additive UI
        # links. Assert them independently before projecting the original complete
        # descriptor into its immutable fingerprint; the old digest oracle stays fixed.
        attachment = {"get_direct_allocation": "allocation", "get_drift_analysis": "drift"}.get(
            tool.name
        )
        if attachment is not None:
            uri = f"ui://trading212-portfolio/{attachment}-v1.html"
            assert descriptor["_meta"].pop("ui") == {
                "resourceUri": uri,
                "visibility": ["model", "app"],
            }
            assert descriptor["_meta"].pop("openai/outputTemplate") == uri
            assert descriptor["_meta"].pop("openai/widgetAccessible") is True
        digest = hashlib.sha256(
            json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert digest == EXPECTED[tool.name], tool.name
