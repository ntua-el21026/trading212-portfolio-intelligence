"""Short root expiry and newly effective license deadlines remain authoritative at return."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session, sessionmaker
from trading212_domain.scenario_execution import ScenarioExecutionInput
from trading212_persistence import scenario_run_capture as capture_module
from trading212_persistence.premium_models import PremiumRunModel
from trading212_persistence.report_authorization import ReportAuthorization
from trading212_persistence.scenario_input_codec import pack_scenario_input, unpack_scenario_input
from trading212_persistence.scenario_input_store import ScenarioInputStore
from trading212_persistence.scenario_models import ScenarioRunModel
from trading212_persistence.scenario_store_types import (
    CapturedScenarioInputs,
    ScenarioStorageError,
    ScenarioStorageErrorCode,
)

from tests.unit.analytics.xray_factories import CUTOFF, uid
from tests.unit.domain.scenario_factories import execution
from tests.unit.persistence.test_scenario_private_stores import authority


@pytest.mark.parametrize("changed", ("root_expiry", "current_license_deadline"))
def test_retained_input_rechecks_expiry_after_private_decode(
    monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    original = execution()
    auth = authority()
    short = CUTOFF.value + timedelta(hours=1)
    retained = replace(original, expires_at=short)
    root = PremiumRunModel(
        id=uid(9940),
        kind="scenario",
        owner_id=auth.owner_id,
        account_id=auth.account_id,
        input_digest=retained.input_digest,
        expires_at=short,
        created_at=CUTOFF.value,
    )
    run = ScenarioRunModel(
        id=root.id,
        owner_id=auth.owner_id,
        account_id=auth.account_id,
        sealed=True,
        **capture_module._header(original),
    )
    now = [CUTOFF.value]
    store = ScenarioInputStore(
        sessionmaker(),
        cursor_signing_key=b"synthetic-key-32-bytes-for-tests!",
        clock=lambda: now[0],
    )
    monkeypatch.setattr(store, "authority", lambda *args, **kwargs: auth)
    monkeypatch.setattr(
        store,
        "_owned",
        lambda session, auth, model, identifier: root if model is PremiumRunModel else run,
    )
    monkeypatch.setattr(ReportAuthorization, "check", lambda *args, **kwargs: None)
    licenses = (uid(999),)
    monkeypatch.setattr(
        store,
        "capture",
        lambda *args, **kwargs: CapturedScenarioInputs(
            value=original, license_version_ids=licenses
        ),
    )
    sources = SimpleNamespace(copy_deadline=original.expires_at)
    refreshed = [0]

    def permit(*args: object, **kwargs: object) -> None:
        refreshed[0] += 1
        if changed == "current_license_deadline" and refreshed[0] > 1:
            sources.copy_deadline = short - timedelta(seconds=1)

    sources._permit = permit
    monkeypatch.setattr(store, "copy_authority", lambda **kwargs: sources)
    payload = pack_scenario_input(retained)
    session = Mock(spec=Session)
    session.scalar.side_effect = (None, payload)
    session.scalars.side_effect = (licenses, (), (), (), ())
    session.execute.return_value.one.return_value = (1, len(payload))
    decode = unpack_scenario_input

    def delayed(value: bytes, *, expected_digest: str) -> ScenarioExecutionInput:
        result = decode(value, expected_digest=expected_digest)
        if changed == "root_expiry":
            now[0] = short + timedelta(seconds=1)
        return result

    monkeypatch.setattr(capture_module, "unpack_scenario_input", delayed)
    with pytest.raises(ScenarioStorageError) as error:
        store.read_retained_input(session, auth, root.id)
    assert error.value.code is ScenarioStorageErrorCode.RUN_EXPIRED
