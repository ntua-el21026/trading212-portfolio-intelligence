"""Concrete research authority defaults preserve explicitly injected fixtures."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_api import main
from trading212_application.premium_provider_status import PremiumProviderConfiguration
from trading212_persistence.acquisition_research_authority import (
    PostgresResearchCapabilityAuthority,
)
from trading212_persistence.premium_provider_status import PostgresPremiumProviderStatusService
from trading212_persistence.research_permissions import ResearchCapabilityAuthority
from trading212_persistence.research_service import PostgresResearchService
from trading212_persistence.source_service import PostgresSourceService
from trading212_security.settings import RuntimeEnvironment, SecuritySettings


@pytest.mark.parametrize("injected", [False, True])
def test_local_composition_uses_real_authority_or_preserves_explicit_override(
    monkeypatch: pytest.MonkeyPatch, injected: bool
) -> None:
    sessions = sessionmaker[Session]()
    monkeypatch.setattr(main, "create_database_engine", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr(main, "create_session_factory", lambda *args: sessions)
    authority = MagicMock(spec=ResearchCapabilityAuthority) if injected else None
    config = PremiumProviderConfiguration(
        outbound_enabled=True, alpha_vantage_credential_port_configured=False
    )
    services = main._local_runtime_defaults(
        SecuritySettings(environment=RuntimeEnvironment.TEST),
        lambda: datetime(2026, 9, 15, tzinfo=UTC),
        cursor_signing_key=b"provider-status-composition-key-32",
        research_capability_authority=authority,
        premium_provider_configuration=config,
    )
    source = next(value for value in services if isinstance(value, PostgresSourceService))
    research = next(value for value in services if isinstance(value, PostgresResearchService))
    status = next(
        value for value in services if isinstance(value, PostgresPremiumProviderStatusService)
    )
    assert source._research_capabilities is research._research_capabilities
    if injected:
        assert source._research_capabilities is authority
    else:
        assert isinstance(source._research_capabilities, PostgresResearchCapabilityAuthority)
    assert status._configuration == config
