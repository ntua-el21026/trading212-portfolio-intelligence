from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from trading212_provider import Trading212Settings

from scripts import smoke_trading212_demo as smoke

CANARY_KEY = "demo-fixture-key"
CANARY_SECRET = "DEMO_CANARY_MUST_NOT_ESCAPE"


def _environment(**overrides: str) -> dict[str, str]:
    result = {
        smoke.EXECUTION_GATE_VARIABLE: "1",
        smoke.CREDENTIAL_BUNDLE_VARIABLE: json.dumps(
            {"api_key": CANARY_KEY, "api_secret": CANARY_SECRET}
        ),
    }
    result.update(overrides)
    return result


@pytest.mark.unit
def test_missing_opt_in_is_external_block_without_credential_resolution(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = smoke.main({smoke.CREDENTIAL_BUNDLE_VARIABLE: f'{{"api_key":"{CANARY_KEY}"}}'})

    output = capsys.readouterr().out
    assert exit_code == 2
    assert json.loads(output) == {
        "environment": "demo",
        "reason": "explicit Demo smoke opt-in is not enabled",
        "result": "blocked_external",
    }
    assert CANARY_KEY not in output


@pytest.mark.unit
@pytest.mark.parametrize(
    "override",
    [
        {smoke.PROVIDER_ENVIRONMENT_VARIABLE: "live"},
        {smoke.LIVE_GATE_VARIABLE: "true"},
        {smoke.PROVIDER_ENVIRONMENT_VARIABLE: "LIVE", smoke.LIVE_GATE_VARIABLE: "1"},
    ],
)
async def test_live_configuration_fails_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
    override: Mapping[str, str],
) -> None:
    constructions = 0

    def construct(**_: object) -> object:
        nonlocal constructions
        constructions += 1
        raise AssertionError("provider client must not be constructed")

    monkeypatch.setattr(smoke, "Trading212Client", construct)

    with pytest.raises(smoke.DemoSmokeConfigurationError):
        await smoke.run_demo_smoke(environment=_environment(**override))
    assert constructions == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "bundle",
    [
        "not-json",
        "[]",
        '{"api_key":"one","api_key":"two","api_secret":"secret"}',
        '{"api_key":"key"}',
        '{"api_key":"key","api_secret":"secret","environment":"demo"}',
        '{"api_key":1,"api_secret":"secret"}',
    ],
)
async def test_bundle_parser_is_strict_and_never_constructs_client(
    monkeypatch: pytest.MonkeyPatch,
    bundle: str,
) -> None:
    constructions = 0

    def construct(**_: object) -> object:
        nonlocal constructions
        constructions += 1
        raise AssertionError("provider client must not be constructed")

    monkeypatch.setattr(smoke, "Trading212Client", construct)

    values = _environment()
    values[smoke.CREDENTIAL_BUNDLE_VARIABLE] = bundle
    with pytest.raises(smoke.DemoSmokeConfigurationError):
        await smoke.run_demo_smoke(environment=values)
    assert constructions == 0


@pytest.mark.unit
async def test_smoke_calls_only_two_demo_reads_and_returns_sanitized_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get_account_summary(self) -> object:
            calls.append("account_summary")
            return SimpleNamespace(
                data=SimpleNamespace(id=2120001, total_value=300),
                status_code=200,
                observed_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
                rate_limit=None,
            )

        async def get_positions(self) -> object:
            calls.append("portfolio_positions")
            return SimpleNamespace(
                data=(),
                status_code=200,
                observed_at=datetime(2026, 8, 31, 12, 0, 1, tzinfo=UTC),
                rate_limit=None,
            )

    monkeypatch.setattr(smoke, "Trading212Client", FakeClient)
    result = await smoke.run_demo_smoke(environment=_environment())
    rendered = json.dumps(result.public_dict())

    settings = captured["settings"]
    assert isinstance(settings, Trading212Settings)
    assert settings.environment.value == "demo"
    assert settings.live_mode_explicitly_enabled is False
    assert settings.max_attempts == 1
    assert settings.base_url == "https://demo.trading212.com/api/v0"
    assert captured["credential_reference"] == "env://T212PI_TRADING212_CREDENTIAL_BUNDLE"
    assert calls == ["account_summary", "portfolio_positions"]
    assert result.environment == "demo"
    assert result.origin == "https://demo.trading212.com"
    assert [check.capability for check in result.checks] == [
        "account_summary",
        "portfolio_positions",
    ]
    assert result.checks[1].record_count == 0
    assert CANARY_KEY not in rendered
    assert CANARY_SECRET not in rendered
    assert "2120001" not in rendered
    assert "totalValue" not in rendered


@pytest.mark.unit
def test_provider_failure_output_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail(**_: object) -> smoke.DemoSmokeResult:
        from trading212_provider import ProviderError, ProviderErrorKind

        raise ProviderError(ProviderErrorKind.AUTHENTICATION, CANARY_SECRET)

    monkeypatch.setattr(smoke, "run_demo_smoke", fail)
    exit_code = smoke.main(_environment())
    output = capsys.readouterr().out

    assert exit_code == 1
    assert json.loads(output) == {
        "environment": "demo",
        "failure_category": "authentication",
        "result": "failed",
    }
    assert CANARY_SECRET not in output
