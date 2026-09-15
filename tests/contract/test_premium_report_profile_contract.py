"""The explicit V3 and V4 boundaries preserves all prior premium components and V1 bytes."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from trading212_api_contracts.typescript import render_premium_report_client, render_report_client

from tests.contract.premium_report_profile_oracle import assert_profiled_path

pytestmark = pytest.mark.contract
BASE = json.loads(
    (Path(__file__).with_name("fixtures") / "premium-report-profile2-baseline.json").read_text()
)


def contract() -> dict[str, Any]:
    value = json.loads(Path("packages/api-contracts/openapi/phase1-v1.json").read_text())
    assert isinstance(value, dict)
    return value


def test_the_same_six_premium_operations_add_only_the_explicit_defaulted_profile_query() -> None:
    source = contract()
    actual = {
        (path, method, value["operationId"])
        for path, methods in source["paths"].items()
        for method, value in methods.items()
        if "premium-reports" in value.get("tags", [])
    }
    expected = {
        (path, method, value["operationId"])
        for path, methods in BASE["paths"].items()
        for method, value in methods.items()
    }
    assert actual == expected
    for path in BASE["paths"]:
        assert_profiled_path(path, source["paths"][path])
    for path, method, _ in actual:
        old = BASE["paths"][path][method]
        current = source["paths"][path][method]
        previous = [
            x
            for x in current.get("parameters", [])
            if not (x["in"] == "query" and x["name"] == "profile")
        ]
        assert previous == old.get("parameters", [])
        profiles = [
            x for x in current["parameters"] if x["in"] == "query" and x["name"] == "profile"
        ]
        assert len(profiles) == 1
        assert profiles[0]["required"] is False
        assert profiles[0]["schema"]["enum"] == [
            "report_sections_v2",
            "report_sections_v3",
            "report_sections_v4",
        ]
        assert profiles[0]["schema"]["default"] == "report_sections_v2"


def test_every_original_profile_two_component_and_shared_v1_client_file_is_unchanged() -> None:
    source = contract()
    for name, expected in BASE["components"].items():
        assert source["components"]["schemas"][name] == expected, name
    for name, expected in BASE["unchanged_files"].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name


def test_profiled_generation_is_deterministic_closed_and_keeps_constructor_type_defaults() -> None:
    source = contract()
    original = deepcopy(source)
    rendered = render_premium_report_client(source)
    assert source == original
    assert rendered == render_premium_report_client(deepcopy(source))
    assert 'P extends PremiumReportProfile = "report_sections_v2"' in rendered
    assert "constructor(options: PremiumReportClientOptions<P>)" in rendered
    assert "body: PremiumReportValue<P," in rendered
    assert "premiumReportSchema(this.#profile," in rendered
    assert "PremiumReportJobStatusV3Schema" in rendered
    assert "PremiumReportPageV3Schema" in rendered
    assert "PremiumReportManifestV3Schema" in rendered
    assert "PremiumReportManifestV4Schema" in rendered
    assert "PremiumReportJobStatusV4Schema" in rendered
    assert "PremiumReportPageV4Schema" in rendered
    assert "z.any(" not in rendered and "z.unknown(" not in rendered
    assert "exports" not in rendered
    assert rendered.count("async ") == 6
    assert "profile_version" in rendered
    legacy = render_report_client(source)
    assert "PremiumReport" not in legacy
    assert "report_sections_v3" not in legacy


@pytest.mark.parametrize("change", ["absent", "duplicate", "unknown", "default", "required"])
def test_generator_rejects_implicit_or_widened_profile_selector(change: str) -> None:
    source = contract()
    operation = source["paths"]["/api/v2/report-jobs"]["post"]
    profile = next(
        x for x in operation["parameters"] if x["in"] == "query" and x["name"] == "profile"
    )
    if change == "absent":
        operation["parameters"].remove(profile)
    elif change == "duplicate":
        operation["parameters"].append(deepcopy(profile))
    elif change == "unknown":
        profile["schema"]["enum"].append("report_sections_unknown")
    elif change == "default":
        profile["schema"]["default"] = "report_sections_v3"
    else:
        profile["required"] = True
    with pytest.raises(ValueError):
        render_premium_report_client(source)


def test_generator_rejects_untyped_success_variants() -> None:
    source = contract()
    schema = source["paths"]["/api/v2/report-jobs"]["post"]["responses"]["202"]["content"][
        "application/json"
    ]["schema"]
    assert "anyOf" in schema
    schema["anyOf"].append({"type": "object"})
    with pytest.raises(ValueError):
        render_premium_report_client(source)
